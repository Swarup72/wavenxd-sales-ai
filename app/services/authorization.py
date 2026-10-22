from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import ReturnDocument

from app.domain.enums import AccessRequestStatus, ProductStatus, UserRole
from app.models.access_request import AccessRequest
from app.models.assignment import CustomerProductAssignment
from app.models.common import utc_now
from app.models.product import Product
from app.models.user import User


def parse_object_id(
    val: Any,
    error_status: int = status.HTTP_404_NOT_FOUND,
    detail: str = "Resource not found",
) -> ObjectId:
    """Safely parses an ObjectId or raises a controlled HTTPException."""
    if isinstance(val, ObjectId):
        return val
    if isinstance(val, str) and ObjectId.is_valid(val):
        return ObjectId(val)
    raise HTTPException(
        status_code=error_status,
        detail=detail,
    )


async def get_verified_product_for_user(
    database: Any,
    user: User,
    product_id: ObjectId | str,
) -> Product:
    """
    Retrieves a product only if the user is authorized to access it.
    - Administrators can view any product.
    - Customer users can only view products if:
        1. An active assignment exists for their company (derived strictly from server-side user).
        2. The product is published and verified.
    Crucially, if the product does not exist, is not assigned, or is not published,
    an identical HTTP 404 error is raised to prevent enumeration or leaking product existence.
    """
    pid = parse_object_id(product_id, error_status=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if user.role == UserRole.ADMIN:
        doc = await database.products.find_one({"_id": pid})
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found",
            )
        return Product(**doc)

    if user.role == UserRole.CUSTOMER:
        if user.company_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customer has no associated company",
            )

        # 1. Verify active customer assignment for user's company
        assignment = await database.customer_product_assignments.find_one(
            {
                "company_id": user.company_id,
                "product_id": pid,
                "is_active": True,
            }
        )
        if not assignment:
            # Raise generic 404 without revealing if the product exists
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found",
            )

        # 2. Verify product exists, is published, and not flagged for technical review
        doc = await database.products.find_one(
            {
                "_id": pid,
                "status": ProductStatus.PUBLISHED,
                "technical_review_required": False,
            }
        )
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found",
            )

        return Product(**doc)

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied",
    )


async def list_accessible_products_for_user(
    database: Any,
    user: User,
) -> list[Product]:
    """
    Lists products accessible to the current user:
    - Administrators receive all products.
    - Customer users receive only actively assigned, published, verified products for their company.
    """
    if user.role == UserRole.ADMIN:
        cursor = database.products.find()
        docs = await cursor.to_list(length=1000)
        return [Product(**doc) for doc in docs]

    if user.role == UserRole.CUSTOMER:
        if user.company_id is None:
            return []

        # Find all active product IDs assigned to this company
        cursor = database.customer_product_assignments.find(
            {"company_id": user.company_id, "is_active": True}
        )
        assignments = await cursor.to_list(length=1000)
        product_ids = [a["product_id"] for a in assignments]

        if not product_ids:
            return []

        # Fetch only published and verified products among assigned IDs
        cursor = database.products.find(
            {
                "_id": {"$in": product_ids},
                "status": ProductStatus.PUBLISHED,
                "technical_review_required": False,
            }
        )
        docs = await cursor.to_list(length=1000)
        return [Product(**doc) for doc in docs]

    return []


async def assign_product_to_company(
    database: Any,
    admin_user: User,
    company_id: ObjectId | str,
    product_id: ObjectId | str,
) -> CustomerProductAssignment:
    """
    Assigns a published, verified product to a company.
    Enforces that target company exists and is active,
    and product is published and verified.
    """
    if admin_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )

    cid = parse_object_id(company_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID")
    pid = parse_object_id(product_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid product ID")

    # 1. Verify company exists and is active
    company = await database.companies.find_one({"_id": cid, "is_active": True})
    if not company:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target company does not exist or is inactive",
        )

    # 2. Verify product exists, is published, and not flagged for review
    product = await database.products.find_one({"_id": pid})
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if product.get("status") != ProductStatus.PUBLISHED or product.get("technical_review_required") is True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only published products eligible for customer access can be assigned",
        )

    now = utc_now()

    # 3. Idempotently upsert assignment
    await database.customer_product_assignments.update_one(
        {
            "company_id": cid,
            "product_id": pid,
        },
        {
            "$set": {
                "is_active": True,
                "assigned_by_user_id": admin_user.id,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        },
        upsert=True,
    )

    doc = await database.customer_product_assignments.find_one(
        {"company_id": cid, "product_id": pid}
    )
    return CustomerProductAssignment(**doc)


async def deactivate_product_assignment(
    database: Any,
    admin_user: User,
    company_id: ObjectId | str,
    product_id: ObjectId | str,
) -> bool:
    """
    Deactivates an existing company product assignment.
    """
    if admin_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )

    cid = parse_object_id(company_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID")
    pid = parse_object_id(product_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid product ID")

    result = await database.customer_product_assignments.update_one(
        {
            "company_id": cid,
            "product_id": pid,
            "is_active": True,
        },
        {
            "$set": {
                "is_active": False,
                "updated_at": utc_now(),
            }
        },
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active product assignment not found for this company",
        )

    return True


async def create_customer_access_request(
    database: Any,
    customer_user: User,
    product_id: ObjectId | str,
    reason: str | None = None,
) -> AccessRequest:
    """
    Creates a new pending access request for a product on behalf of the customer's company.
    Derives company_id strictly from the authenticated customer_user.
    Does not leak whether a non-existent product exists.
    """
    if customer_user.role != UserRole.CUSTOMER or customer_user.company_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer company access required",
        )

    pid = parse_object_id(product_id, error_status=status.HTTP_404_NOT_FOUND, detail="Product not found")

    # Verify product exists, is published, and not flagged for review
    product = await database.products.find_one(
        {
            "_id": pid,
            "status": ProductStatus.PUBLISHED,
            "technical_review_required": False,
        }
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Check if already actively assigned
    existing_assign = await database.customer_product_assignments.find_one(
        {
            "company_id": customer_user.company_id,
            "product_id": pid,
            "is_active": True,
        }
    )
    if existing_assign:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product is already assigned to your company",
        )

    # Check if a request is already pending
    pending_req = await database.access_requests.find_one(
        {
            "company_id": customer_user.company_id,
            "product_id": pid,
            "status": AccessRequestStatus.PENDING,
        }
    )
    if pending_req:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An access request for this product is already pending review",
        )

    now = utc_now()
    clean_reason = reason.strip() if reason and reason.strip() else None

    req = AccessRequest(
        company_id=customer_user.company_id,
        requested_by_user_id=customer_user.id,
        product_id=pid,
        reason=clean_reason,
        status=AccessRequestStatus.PENDING,
        created_at=now,
        updated_at=now,
    )

    doc = req.model_dump(by_alias=True, exclude={"id"})
    result = await database.access_requests.insert_one(doc)
    req.id = result.inserted_id
    return req


async def approve_access_request(
    database: Any,
    admin_user: User,
    request_id: ObjectId | str,
    review_note: str | None = None,
) -> CustomerProductAssignment:
    """
    Administrator workflow to approve an access request and activate customer product assignment.
    Validates company and product eligibility.
    Uses atomic conditional update to guarantee single reviewer race safety.
    Enforces uniqueness of company/product assignment via atomic upsert.
    """
    if admin_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required to approve requests",
        )

    req_id = parse_object_id(request_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid access request ID")
    req_doc = await database.access_requests.find_one({"_id": req_id})
    if not req_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access request not found",
        )

    access_request = AccessRequest(**req_doc)
    if access_request.status != AccessRequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Access request has already been reviewed (status: {access_request.status})",
        )

    # 1. Verify company is valid and active
    company = await database.companies.find_one({"_id": access_request.company_id, "is_active": True})
    if not company:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target company does not exist or is inactive",
        )

    # 2. Verify product is published and eligible
    product = await database.products.find_one({"_id": access_request.product_id})
    if not product or product.get("status") != ProductStatus.PUBLISHED or product.get("technical_review_required") is True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product is not eligible for customer access",
        )

    now = utc_now()
    clean_note = review_note.strip() if review_note and review_note.strip() else None

    # 3. Atomic transition from PENDING -> APPROVED
    updated_doc = await database.access_requests.find_one_and_update(
        {
            "_id": req_id,
            "status": AccessRequestStatus.PENDING,
        },
        {
            "$set": {
                "status": AccessRequestStatus.APPROVED,
                "reviewed_by_user_id": admin_user.id,
                "review_note": clean_note,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )

    if not updated_doc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Access request was already reviewed by another administrator",
        )

    # 4. Upsert active customer product assignment
    await database.customer_product_assignments.update_one(
        {
            "company_id": access_request.company_id,
            "product_id": access_request.product_id,
        },
        {
            "$set": {
                "is_active": True,
                "assigned_by_user_id": admin_user.id,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        },
        upsert=True,
    )

    assign_doc = await database.customer_product_assignments.find_one(
        {
            "company_id": access_request.company_id,
            "product_id": access_request.product_id,
        }
    )
    return CustomerProductAssignment(**assign_doc)


async def reject_access_request(
    database: Any,
    admin_user: User,
    request_id: ObjectId | str,
    review_note: str | None = None,
) -> AccessRequest:
    """
    Administrator workflow to reject an access request.
    Does NOT create any assignment.
    Uses atomic conditional update to guarantee single reviewer race safety.
    """
    if admin_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required to reject requests",
        )

    req_id = parse_object_id(request_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid access request ID")
    req_doc = await database.access_requests.find_one({"_id": req_id})
    if not req_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access request not found",
        )

    access_request = AccessRequest(**req_doc)
    if access_request.status != AccessRequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Access request has already been reviewed (status: {access_request.status})",
        )

    now = utc_now()
    clean_note = review_note.strip() if review_note and review_note.strip() else None

    # Atomic transition from PENDING -> REJECTED
    updated_doc = await database.access_requests.find_one_and_update(
        {
            "_id": req_id,
            "status": AccessRequestStatus.PENDING,
        },
        {
            "$set": {
                "status": AccessRequestStatus.REJECTED,
                "reviewed_by_user_id": admin_user.id,
                "review_note": clean_note,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )

    if not updated_doc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Access request was already reviewed by another administrator",
        )

    return AccessRequest(**updated_doc)
