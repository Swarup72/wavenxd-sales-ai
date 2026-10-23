import csv
import io
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.core.config import get_settings
from app.core.dependencies import (
    get_database,
    require_admin_user,
    validate_csrf,
)
from app.core.security import hash_password, validate_password_strength
from app.domain.enums import AccessRequestStatus, LeadStage, ProductStatus, UserRole
from app.models.common import utc_now
from app.models.company import Company
from app.models.lead import Lead, LeadResponse, UpdateLeadStageRequest
from app.models.product import Product
from app.models.recommendation import CustomerRequirements, RecommendationResult
from app.models.user import User
from app.services.audit_service import list_audit_events, record_audit_event
from app.services.authorization import (
    approve_access_request,
    assign_product_to_company,
    deactivate_product_assignment,
    parse_object_id,
    reject_access_request,
)
from app.services.invitation_service import create_invitation, InvitationError
from app.services.recommendation_engine import evaluate_recommendations

router = APIRouter(prefix="/admin", tags=["Admin Portal & Operations"])


# --- Schemas ---

class CompanyResponse(BaseModel):
    id: str
    name: str
    is_active: bool
    contact_email: str | None = None
    notes: str | None = None


class CompanyDetailResponse(BaseModel):
    id: str
    name: str
    is_active: bool
    contact_email: str | None = None
    notes: str | None = None
    user_count: int = 0
    assignment_count: int = 0
    created_at: str | None = None


class CompanyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact_email: EmailStr | None = None
    notes: str | None = Field(default=None, max_length=2000)


class CompanyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_email: EmailStr | None = None
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class UserAdminResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    company_id: str | None = None
    company_name: str | None = None
    is_active: bool
    must_change_password: bool
    created_at: str
    updated_at: str


class UserAdminUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class AdminResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class InvitationAdminResponse(BaseModel):
    id: str
    email: str
    company_id: str
    company_name: str | None = None
    status: str
    expires_at: str
    created_at: str


class ProductAdminResponse(BaseModel):
    id: str
    name: str
    catalog_key: str | None = None
    category: str | None = None
    spray_pattern: str | None = None
    feed_configuration: str | None = None
    frequency_khz: float | None = None
    droplet_size_um: float | None = None
    flow_rate_max_ml_min: float | None = None
    flow_rate_description: str | None = None
    viscosity_max_cp: float | None = None
    viscosity_description: str | None = None
    applications: list[str] = []
    status: ProductStatus
    technical_review_required: bool
    catalog_notes: str | None = None


class ProductUpdateRequest(BaseModel):
    name: str | None = None
    status: ProductStatus | None = None
    technical_review_required: bool | None = None
    flow_rate_max_ml_min: float | None = None
    viscosity_max_cp: float | None = None
    catalog_notes: str | None = None


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    catalog_key: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    spray_pattern: str | None = None
    feed_configuration: str | None = None
    frequency_khz: float | None = Field(default=None, gt=0)
    droplet_size_um: float | None = Field(default=None, gt=0)
    flow_rate_min_ml_min: float | None = Field(default=None, ge=0)
    flow_rate_max_ml_min: float | None = Field(default=None, gt=0)
    flow_rate_description: str | None = None
    viscosity_max_cp: float | None = Field(default=None, gt=0)
    viscosity_description: str | None = None
    applications: list[str] = Field(default_factory=list)
    status: ProductStatus = ProductStatus.DRAFT
    technical_review_required: bool = True
    catalog_notes: str | None = None


class CompanyProductItemResponse(BaseModel):
    product: ProductAdminResponse
    is_active: bool
    assignment_id: str


class AssignmentResponse(BaseModel):
    id: str
    company_id: str
    product_id: str
    is_active: bool
    assigned_by_user_id: str
    message: str = "Assignment updated successfully"


class AssignmentDetailResponse(BaseModel):
    id: str
    company_id: str
    company_name: str
    product_id: str
    product_name: str
    product_catalog_key: str | None = None
    is_active: bool
    assigned_by_user_id: str
    created_at: str


class AdminCreateInvitationRequest(BaseModel):
    email: EmailStr
    company_id: str


class AdminConversationResponse(BaseModel):
    id: str
    company_id: str
    company_name: str
    user_id: str
    user_email: str | None = None
    title: str | None = None
    message_count: int
    status: str
    created_at: str
    updated_at: str


class AdminConversationDetailResponse(BaseModel):
    id: str
    company_id: str
    company_name: str
    user_id: str
    user_email: str | None = None
    title: str | None = None
    status: str
    messages: list[dict[str, Any]]
    created_at: str
    updated_at: str


class AccessRequestAdminResponse(BaseModel):
    id: str
    company_id: str
    requested_by_user_id: str
    product_id: str
    reason: str | None = None
    status: AccessRequestStatus
    reviewed_by_user_id: str | None = None
    review_note: str | None = None
    created_at: str
    updated_at: str


class ReviewRequest(BaseModel):
    review_note: str | None = Field(default=None, max_length=2000)


class ProviderStatusResponse(BaseModel):
    primary_llm: str
    primary_model: str
    fallback_llm: str | None = None
    fallback_enabled: bool
    stt_provider: str
    stt_model: str
    tts_provider: str
    tts_model: str
    environment: str
    budget_mode: str = "₹0 Prototype (Free tier / local only)"


class OverviewStatsResponse(BaseModel):
    total_companies: int
    active_companies: int
    total_users: int
    active_users: int
    total_products: int
    published_products: int
    review_required_products: int
    active_assignments: int
    pending_access_requests: int
    primary_provider: str


def build_product_admin_response(p: Product) -> ProductAdminResponse:
    return ProductAdminResponse(
        id=str(p.id),
        name=p.name,
        catalog_key=p.catalog_key,
        category=p.category,
        spray_pattern=p.spray_pattern,
        feed_configuration=p.feed_configuration,
        frequency_khz=p.frequency_khz,
        droplet_size_um=p.droplet_size_um,
        flow_rate_max_ml_min=p.flow_rate_max_ml_min,
        flow_rate_description=p.flow_rate_description,
        viscosity_max_cp=p.viscosity_max_cp,
        viscosity_description=p.viscosity_description,
        applications=p.applications,
        status=p.status,
        technical_review_required=p.technical_review_required,
        catalog_notes=p.catalog_notes,
    )


# --- Endpoints ---

# 1. Overview Dashboard Metrics
@router.get(
    "/overview",
    response_model=OverviewStatsResponse,
    dependencies=[Depends(require_admin_user)],
    summary="Get operational metrics for admin dashboard",
)
async def get_admin_overview(database: Any = Depends(get_database)):
    total_companies = await database.companies.count_documents({})
    active_companies = await database.companies.count_documents({"is_active": True})
    total_users = await database.users.count_documents({})
    active_users = await database.users.count_documents({"is_active": True})
    total_products = await database.products.count_documents({})
    published_products = await database.products.count_documents({"status": ProductStatus.PUBLISHED})
    review_required_products = await database.products.count_documents({"technical_review_required": True})
    active_assignments = await database.customer_product_assignments.count_documents({"is_active": True})
    pending_access_requests = await database.access_requests.count_documents({"status": AccessRequestStatus.PENDING})

    return OverviewStatsResponse(
        total_companies=total_companies,
        active_companies=active_companies,
        total_users=total_users,
        active_users=active_users,
        total_products=total_products,
        published_products=published_products,
        review_required_products=review_required_products,
        active_assignments=active_assignments,
        pending_access_requests=pending_access_requests,
        primary_provider=get_settings().llm_provider,
    )


# 2. Company Management
@router.get(
    "/companies",
    response_model=list[CompanyResponse],
    dependencies=[Depends(require_admin_user)],
    summary="List customer companies",
)
async def list_companies(database: Any = Depends(get_database)):
    cursor = database.companies.find().sort("name", 1)
    docs = await cursor.to_list(length=1000)
    return [
        CompanyResponse(
            id=str(c["_id"]),
            name=c["name"],
            is_active=c.get("is_active", True),
            contact_email=c.get("contact_email"),
            notes=c.get("notes"),
        )
        for c in docs
    ]


@router.post(
    "/companies",
    response_model=CompanyResponse,
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Create a new customer company",
)
async def create_company_endpoint(
    body: CompanyCreateRequest,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    name = body.name.strip()
    existing = await database.companies.find_one({"name": name})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Company with name '{name}' already exists",
        )
    now = utc_now()
    comp = Company(
        name=name,
        contact_email=str(body.contact_email) if body.contact_email else None,
        notes=body.notes,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    doc = comp.model_dump(by_alias=True, exclude={"id"})
    res = await database.companies.insert_one(doc)
    cid = res.inserted_id

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="CREATE_COMPANY",
        target_type="company",
        target_id=cid,
        details=f"Created company '{name}'",
    )

    return CompanyResponse(
        id=str(cid),
        name=comp.name,
        is_active=comp.is_active,
        contact_email=comp.contact_email,
        notes=comp.notes,
    )


@router.get(
    "/companies/{company_id}",
    response_model=CompanyDetailResponse,
    dependencies=[Depends(require_admin_user)],
    summary="Get details of a company including users and assigned product counts",
)
async def get_company_detail(
    company_id: str,
    database: Any = Depends(get_database),
):
    cid = parse_object_id(company_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID")
    doc = await database.companies.find_one({"_id": cid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    user_count = await database.users.count_documents({"company_id": cid})
    assignment_count = await database.customer_product_assignments.count_documents(
        {"company_id": cid, "is_active": True}
    )

    created_at = doc.get("created_at", utc_now())
    created_at_str = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)

    return CompanyDetailResponse(
        id=str(doc["_id"]),
        name=doc["name"],
        is_active=doc.get("is_active", True),
        contact_email=doc.get("contact_email"),
        notes=doc.get("notes"),
        user_count=user_count,
        assignment_count=assignment_count,
        created_at=created_at_str,
    )


@router.patch(
    "/companies/{company_id}",
    response_model=CompanyResponse,
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Update an existing company",
)
async def update_company_endpoint(
    company_id: str,
    body: CompanyUpdateRequest,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    cid = parse_object_id(company_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID")
    existing = await database.companies.find_one({"_id": cid})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    update_fields: dict[str, Any] = {"updated_at": utc_now()}
    if body.name is not None:
        name = body.name.strip()
        conflict = await database.companies.find_one({"name": name, "_id": {"$ne": cid}})
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Company with name '{name}' already exists",
            )
        update_fields["name"] = name
    if body.contact_email is not None:
        update_fields["contact_email"] = str(body.contact_email)
    if body.notes is not None:
        update_fields["notes"] = body.notes
    if body.is_active is not None:
        update_fields["is_active"] = body.is_active

    await database.companies.update_one({"_id": cid}, {"$set": update_fields})
    updated_doc = await database.companies.find_one({"_id": cid})

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="UPDATE_COMPANY",
        target_type="company",
        target_id=cid,
        details=f"Updated company '{updated_doc['name']}'",
    )

    return CompanyResponse(
        id=str(updated_doc["_id"]),
        name=updated_doc["name"],
        is_active=updated_doc.get("is_active", True),
        contact_email=updated_doc.get("contact_email"),
        notes=updated_doc.get("notes"),
    )


# 3. User & Invitation Management
@router.get(
    "/users",
    response_model=list[UserAdminResponse],
    dependencies=[Depends(require_admin_user)],
    summary="List all users with roles and company associations",
)
async def list_users_endpoint(database: Any = Depends(get_database)):
    cursor = database.users.find().sort("created_at", -1)
    docs = await cursor.to_list(length=1000)

    companies_cursor = database.companies.find()
    companies_docs = await companies_cursor.to_list(length=1000)
    company_map = {str(c["_id"]): c["name"] for c in companies_docs}

    results: list[UserAdminResponse] = []
    for d in docs:
        cid_str = str(d["company_id"]) if d.get("company_id") else None
        cname = company_map.get(cid_str) if cid_str else None
        c_at = d.get("created_at", utc_now())
        u_at = d.get("updated_at", utc_now())
        results.append(
            UserAdminResponse(
                id=str(d["_id"]),
                email=d["email"],
                full_name=d["full_name"],
                role=d["role"],
                company_id=cid_str,
                company_name=cname,
                is_active=d.get("is_active", True),
                must_change_password=d.get("must_change_password", False),
                created_at=c_at.isoformat() if hasattr(c_at, "isoformat") else str(c_at),
                updated_at=u_at.isoformat() if hasattr(u_at, "isoformat") else str(u_at),
            )
        )
    return results


@router.patch(
    "/users/{user_id}",
    response_model=UserAdminResponse,
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Update user profile or activation status (cannot deactivate last admin)",
)
async def update_user_endpoint(
    user_id: str,
    body: UserAdminUpdateRequest,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    uid = parse_object_id(user_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID")
    target_user_doc = await database.users.find_one({"_id": uid})
    if not target_user_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    target_user = User(**target_user_doc)

    # Protect against deactivating the last active administrator
    if body.is_active is False and target_user.role == UserRole.ADMIN:
        active_admins_count = await database.users.count_documents(
            {"role": UserRole.ADMIN, "is_active": True}
        )
        if active_admins_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate the last active administrator account",
            )

    update_fields: dict[str, Any] = {"updated_at": utc_now()}
    if body.full_name is not None:
        update_fields["full_name"] = body.full_name.strip()
    if body.is_active is not None:
        update_fields["is_active"] = body.is_active

    await database.users.update_one({"_id": uid}, {"$set": update_fields})
    updated_doc = await database.users.find_one({"_id": uid})

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="UPDATE_USER",
        target_type="user",
        target_id=uid,
        details=f"Updated user '{updated_doc['email']}' (active={updated_doc.get('is_active')})",
    )

    cid_str = str(updated_doc["company_id"]) if updated_doc.get("company_id") else None
    cname = None
    if cid_str:
        comp = await database.companies.find_one({"_id": updated_doc["company_id"]})
        if comp:
            cname = comp["name"]

    c_at = updated_doc.get("created_at", utc_now())
    u_at = updated_doc.get("updated_at", utc_now())

    return UserAdminResponse(
        id=str(updated_doc["_id"]),
        email=updated_doc["email"],
        full_name=updated_doc["full_name"],
        role=updated_doc["role"],
        company_id=cid_str,
        company_name=cname,
        is_active=updated_doc.get("is_active", True),
        must_change_password=updated_doc.get("must_change_password", False),
        created_at=c_at.isoformat() if hasattr(c_at, "isoformat") else str(c_at),
        updated_at=u_at.isoformat() if hasattr(u_at, "isoformat") else str(u_at),
    )


@router.post(
    "/users/{user_id}/reset-password",
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Safely reset a user password via Argon2id",
)
async def admin_reset_password_endpoint(
    user_id: str,
    body: AdminResetPasswordRequest,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    uid = parse_object_id(user_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID")
    target_user_doc = await database.users.find_one({"_id": uid})
    if not target_user_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    valid, err_msg = validate_password_strength(body.password)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)

    new_hash = hash_password(body.password)
    await database.users.update_one(
        {"_id": uid},
        {
            "$set": {
                "password_hash": new_hash,
                "must_change_password": False,
                "updated_at": utc_now(),
            }
        },
    )

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="RESET_PASSWORD",
        target_type="user",
        target_id=uid,
        details=f"Admin reset password for user '{target_user_doc['email']}'",
    )

    return {"status": "ok", "message": f"Password successfully reset for {target_user_doc['email']}"}


@router.get(
    "/invitations",
    response_model=list[InvitationAdminResponse],
    dependencies=[Depends(require_admin_user)],
    summary="List customer invitations with company information",
)
async def list_invitations_endpoint(database: Any = Depends(get_database)):
    cursor = database.invitations.find().sort("created_at", -1)
    docs = await cursor.to_list(length=1000)

    companies_cursor = database.companies.find()
    companies_docs = await companies_cursor.to_list(length=1000)
    company_map = {str(c["_id"]): c["name"] for c in companies_docs}

    results: list[InvitationAdminResponse] = []
    for d in docs:
        cid_str = str(d["company_id"])
        cname = company_map.get(cid_str)
        exp = d.get("expires_at", utc_now())
        cre = d.get("created_at", utc_now())
        results.append(
            InvitationAdminResponse(
                id=str(d["_id"]),
                email=d["email"],
                company_id=cid_str,
                company_name=cname,
                status=d["status"] if isinstance(d["status"], str) else d["status"].value,
                expires_at=exp.isoformat() if hasattr(exp, "isoformat") else str(exp),
                created_at=cre.isoformat() if hasattr(cre, "isoformat") else str(cre),
            )
        )
    return results


@router.post(
    "/invitations",
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Create a customer invitation token",
)
async def create_invitation_endpoint(
    body: AdminCreateInvitationRequest,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    cid = parse_object_id(body.company_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID")
    try:
        invitation, raw_token = await create_invitation(
            database=database,
            email=body.email,
            company_id=cid,
            invited_by_user_id=current_admin.id,
        )
    except InvitationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="CREATE_INVITATION",
        target_type="invitation",
        target_id=str(invitation.id),
        details=f"Created invitation for email '{body.email}' under company {body.company_id}",
    )

    return {
        "id": str(invitation.id),
        "email": invitation.email,
        "company_id": str(invitation.company_id),
        "invitation_token": raw_token,
        "expires_at": invitation.expires_at.isoformat(),
        "message": "Invitation created successfully",
    }


# 4. Product Catalog Management
@router.get(
    "/products",
    response_model=list[ProductAdminResponse],
    dependencies=[Depends(require_admin_user)],
    summary="List all catalog products with status and review flags",
)
async def list_catalog_products(database: Any = Depends(get_database)):
    cursor = database.products.find().sort("name", 1)
    docs = await cursor.to_list(length=1000)
    return [build_product_admin_response(Product(**d)) for d in docs]


@router.post(
    "/products",
    response_model=ProductAdminResponse,
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Create a new catalog product (Admin only)",
)
async def create_catalog_product(
    body: ProductCreateRequest,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    if body.catalog_key:
        existing = await database.products.find_one({"catalog_key": body.catalog_key})
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product with catalog key '{body.catalog_key}' already exists",
            )

    now = utc_now()
    new_prod = Product(
        name=body.name.strip(),
        catalog_key=body.catalog_key,
        category=body.category,
        spray_pattern=body.spray_pattern,
        feed_configuration=body.feed_configuration,
        frequency_khz=body.frequency_khz,
        droplet_size_um=body.droplet_size_um,
        flow_rate_min_ml_min=body.flow_rate_min_ml_min,
        flow_rate_max_ml_min=body.flow_rate_max_ml_min,
        flow_rate_description=body.flow_rate_description,
        viscosity_max_cp=body.viscosity_max_cp,
        viscosity_description=body.viscosity_description,
        applications=body.applications,
        status=body.status,
        technical_review_required=body.technical_review_required,
        catalog_notes=body.catalog_notes,
        created_at=now,
        updated_at=now,
    )

    doc = new_prod.model_dump(by_alias=True, exclude={"id"})
    result = await database.products.insert_one(doc)
    new_prod.id = result.inserted_id

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="CREATE_PRODUCT",
        target_type="product",
        target_id=new_prod.id,
        details=f"Created product '{new_prod.name}' (status={new_prod.status}, review_required={new_prod.technical_review_required})",
    )

    return build_product_admin_response(new_prod)


@router.get(
    "/products/{product_id}",
    response_model=ProductAdminResponse,
    dependencies=[Depends(require_admin_user)],
    summary="Get details of a single product",
)
async def get_product_detail(
    product_id: str,
    database: Any = Depends(get_database),
):
    pid = parse_object_id(product_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid product ID")
    doc = await database.products.find_one({"_id": pid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return build_product_admin_response(Product(**doc))


@router.patch(
    "/products/{product_id}",
    response_model=ProductAdminResponse,
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Update product status or technical review flag",
)
async def update_product_endpoint(
    product_id: str,
    body: ProductUpdateRequest,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    pid = parse_object_id(product_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid product ID")
    doc = await database.products.find_one({"_id": pid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    update_fields: dict[str, Any] = {"updated_at": utc_now()}
    if body.status is not None:
        update_fields["status"] = body.status
    if body.technical_review_required is not None:
        update_fields["technical_review_required"] = body.technical_review_required
    if body.catalog_notes is not None:
        update_fields["catalog_notes"] = body.catalog_notes
    if body.name is not None:
        update_fields["name"] = body.name.strip()
    if body.flow_rate_max_ml_min is not None:
        update_fields["flow_rate_max_ml_min"] = body.flow_rate_max_ml_min
    if body.viscosity_max_cp is not None:
        update_fields["viscosity_max_cp"] = body.viscosity_max_cp

    await database.products.update_one({"_id": pid}, {"$set": update_fields})
    updated_doc = await database.products.find_one({"_id": pid})

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="UPDATE_PRODUCT",
        target_type="product",
        target_id=pid,
        details=f"Updated product '{updated_doc['name']}' status={updated_doc['status']} review_req={updated_doc['technical_review_required']}",
    )

    return build_product_admin_response(Product(**updated_doc))


@router.post(
    "/products/{product_id}/clear-review",
    response_model=ProductAdminResponse,
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Approve technical review and publish product",
)
async def clear_product_review_endpoint(
    product_id: str,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    pid = parse_object_id(product_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid product ID")
    doc = await database.products.find_one({"_id": pid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    await database.products.update_one(
        {"_id": pid},
        {"$set": {"technical_review_required": False, "status": ProductStatus.PUBLISHED, "updated_at": utc_now()}},
    )
    updated_doc = await database.products.find_one({"_id": pid})

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="APPROVE_TECHNICAL_REVIEW",
        target_type="product",
        target_id=pid,
        details=f"Approved technical review and published product '{updated_doc['name']}'",
    )

    return build_product_admin_response(Product(**updated_doc))


# 5. Company Product Assignments
@router.get(
    "/assignments",
    response_model=list[AssignmentDetailResponse],
    dependencies=[Depends(require_admin_user)],
    summary="List all company product assignments across the system",
)
async def list_all_assignments(
    company_id: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    database: Any = Depends(get_database),
):
    query: dict[str, Any] = {}
    if company_id:
        cid = parse_object_id(company_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID")
        query["company_id"] = cid
    if is_active is not None:
        query["is_active"] = is_active

    cursor = database.customer_product_assignments.find(query).sort("created_at", -1)
    assignments = await cursor.to_list(length=1000)

    comp_docs = await database.companies.find().to_list(length=1000)
    company_map = {str(c["_id"]): c["name"] for c in comp_docs}

    prod_docs = await database.products.find().to_list(length=1000)
    prod_map = {str(p["_id"]): p for p in prod_docs}

    results: list[AssignmentDetailResponse] = []
    for a in assignments:
        cid_str = str(a["company_id"])
        pid_str = str(a["product_id"])
        prod = prod_map.get(pid_str)
        cname = company_map.get(cid_str, "Unknown Company")
        pname = prod["name"] if prod else "Unknown Product"
        pkey = prod.get("catalog_key") if prod else None
        c_at = a.get("created_at", utc_now())

        results.append(
            AssignmentDetailResponse(
                id=str(a["_id"]),
                company_id=cid_str,
                company_name=cname,
                product_id=pid_str,
                product_name=pname,
                product_catalog_key=pkey,
                is_active=a.get("is_active", True),
                assigned_by_user_id=str(a.get("assigned_by_user_id", "")),
                created_at=c_at.isoformat() if hasattr(c_at, "isoformat") else str(c_at),
            )
        )
    return results


@router.get(
    "/companies/{company_id}/products",
    response_model=list[CompanyProductItemResponse],
    dependencies=[Depends(require_admin_user)],
    summary="View products assigned to a specific company",
)
async def list_company_products(
    company_id: str,
    database: Any = Depends(get_database),
):
    cid = parse_object_id(company_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID")

    company = await database.companies.find_one({"_id": cid})
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found",
        )

    cursor = database.customer_product_assignments.find({"company_id": cid})
    assignments = await cursor.to_list(length=1000)

    items: list[CompanyProductItemResponse] = []
    for a in assignments:
        prod_doc = await database.products.find_one({"_id": a["product_id"]})
        if prod_doc:
            items.append(
                CompanyProductItemResponse(
                    product=build_product_admin_response(Product(**prod_doc)),
                    is_active=a.get("is_active", True),
                    assignment_id=str(a["_id"]),
                )
            )
    return items


@router.post(
    "/companies/{company_id}/products/{product_id}",
    response_model=AssignmentResponse,
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Assign a published, verified product to a company",
)
async def assign_product(
    company_id: str,
    product_id: str,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    assignment = await assign_product_to_company(
        database=database,
        admin_user=current_admin,
        company_id=company_id,
        product_id=product_id,
    )

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="ASSIGN_PRODUCT",
        target_type="assignment",
        target_id=str(assignment.id),
        details=f"Assigned product {product_id} to company {company_id}",
    )

    return AssignmentResponse(
        id=str(assignment.id),
        company_id=str(assignment.company_id),
        product_id=str(assignment.product_id),
        is_active=assignment.is_active,
        assigned_by_user_id=str(assignment.assigned_by_user_id),
        message="Product successfully assigned to company",
    )


@router.delete(
    "/companies/{company_id}/products/{product_id}",
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Deactivate a company's product assignment",
)
async def remove_assignment(
    company_id: str,
    product_id: str,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    await deactivate_product_assignment(
        database=database,
        admin_user=current_admin,
        company_id=company_id,
        product_id=product_id,
    )

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="DEACTIVATE_ASSIGNMENT",
        target_type="assignment",
        target_id=f"{company_id}:{product_id}",
        details=f"Deactivated product {product_id} assignment for company {company_id}",
    )

    return {"status": "ok", "message": "Product assignment deactivated"}


# 6. Review Queue & Access Requests
@router.get(
    "/technical-review-queue",
    dependencies=[Depends(require_admin_user)],
    summary="Retrieve flagged products and pending requests requiring review",
)
async def get_technical_review_queue(database: Any = Depends(get_database)):
    flagged_cursor = database.products.find({"technical_review_required": True})
    flagged_prods = await flagged_cursor.to_list(length=100)

    req_cursor = database.access_requests.find({"status": AccessRequestStatus.PENDING}).sort("created_at", -1)
    pending_reqs = await req_cursor.to_list(length=100)

    return {
        "flagged_products": [build_product_admin_response(Product(**p)) for p in flagged_prods],
        "pending_requests_count": len(pending_reqs),
        "flagged_products_count": len(flagged_prods),
    }


@router.get(
    "/access-requests",
    response_model=list[AccessRequestAdminResponse],
    dependencies=[Depends(require_admin_user)],
    summary="List customer access requests",
)
async def list_access_requests(
    status_filter: AccessRequestStatus | None = Query(default=None, alias="status"),
    database: Any = Depends(get_database),
):
    query: dict[str, Any] = {}
    if status_filter:
        query["status"] = status_filter

    cursor = database.access_requests.find(query).sort("created_at", -1)
    docs = await cursor.to_list(length=1000)

    return [
        AccessRequestAdminResponse(
            id=str(d["_id"]),
            company_id=str(d["company_id"]),
            requested_by_user_id=str(d["requested_by_user_id"]),
            product_id=str(d["product_id"]),
            reason=d.get("reason"),
            status=d["status"],
            reviewed_by_user_id=str(d["reviewed_by_user_id"]) if d.get("reviewed_by_user_id") else None,
            review_note=d.get("review_note"),
            created_at=d["created_at"].isoformat() if hasattr(d["created_at"], "isoformat") else str(d["created_at"]),
            updated_at=d["updated_at"].isoformat() if hasattr(d["updated_at"], "isoformat") else str(d["updated_at"]),
        )
        for d in docs
    ]


@router.get(
    "/access-requests/{request_id}",
    response_model=AccessRequestAdminResponse,
    dependencies=[Depends(require_admin_user)],
    summary="View details of a specific access request",
)
async def get_access_request(
    request_id: str,
    database: Any = Depends(get_database),
):
    req_id = parse_object_id(request_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid access request ID")
    doc = await database.access_requests.find_one({"_id": req_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access request not found",
        )

    return AccessRequestAdminResponse(
        id=str(doc["_id"]),
        company_id=str(doc["company_id"]),
        requested_by_user_id=str(doc["requested_by_user_id"]),
        product_id=str(doc["product_id"]),
        reason=doc.get("reason"),
        status=doc["status"],
        reviewed_by_user_id=str(doc["reviewed_by_user_id"]) if doc.get("reviewed_by_user_id") else None,
        review_note=doc.get("review_note"),
        created_at=doc["created_at"].isoformat() if hasattr(doc["created_at"], "isoformat") else str(doc["created_at"]),
        updated_at=doc["updated_at"].isoformat() if hasattr(doc["updated_at"], "isoformat") else str(doc["updated_at"]),
    )


@router.post(
    "/access-requests/{request_id}/approve",
    response_model=AssignmentResponse,
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Approve an access request and grant entitlement",
)
async def approve_request_endpoint(
    request_id: str,
    body: ReviewRequest = ReviewRequest(),
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    assignment = await approve_access_request(
        database=database,
        admin_user=current_admin,
        request_id=request_id,
        review_note=body.review_note,
    )

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="APPROVE_ACCESS_REQUEST",
        target_type="access_request",
        target_id=request_id,
        details=f"Approved access request {request_id}",
    )

    return AssignmentResponse(
        id=str(assignment.id),
        company_id=str(assignment.company_id),
        product_id=str(assignment.product_id),
        is_active=assignment.is_active,
        assigned_by_user_id=str(assignment.assigned_by_user_id),
        message="Access request approved and product entitlement granted",
    )


@router.post(
    "/access-requests/{request_id}/reject",
    response_model=AccessRequestAdminResponse,
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Reject an access request without granting access",
)
async def reject_request_endpoint(
    request_id: str,
    body: ReviewRequest = ReviewRequest(),
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    rejected_req = await reject_access_request(
        database=database,
        admin_user=current_admin,
        request_id=request_id,
        review_note=body.review_note,
    )

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="REJECT_ACCESS_REQUEST",
        target_type="access_request",
        target_id=request_id,
        details=f"Rejected access request {request_id}",
    )

    return AccessRequestAdminResponse(
        id=str(rejected_req.id),
        company_id=str(rejected_req.company_id),
        requested_by_user_id=str(rejected_req.requested_by_user_id),
        product_id=str(rejected_req.product_id),
        reason=rejected_req.reason,
        status=rejected_req.status,
        reviewed_by_user_id=str(rejected_req.reviewed_by_user_id) if rejected_req.reviewed_by_user_id else None,
        review_note=rejected_req.review_note,
        created_at=rejected_req.created_at.isoformat(),
        updated_at=rejected_req.updated_at.isoformat(),
    )


# 7. Diagnostic Recommendations Evaluation
@router.post(
    "/recommendations/evaluate",
    response_model=RecommendationResult,
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Diagnostic recommendation evaluation across entire catalog or specific company",
)
async def admin_diagnostic_recommendations(
    requirements: CustomerRequirements,
    company_id: str | None = Query(default=None),
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    if company_id:
        cid = parse_object_id(company_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID")
        company = await database.companies.find_one({"_id": cid})
        if not company:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
        cursor = database.customer_product_assignments.find({"company_id": cid, "is_active": True})
        assigns = await cursor.to_list(length=1000)
        pids = [a["product_id"] for a in assigns]
        cursor = database.products.find({"_id": {"$in": pids}})
        docs = await cursor.to_list(length=1000)
        candidate_products = [Product(**d) for d in docs]
    else:
        cursor = database.products.find()
        docs = await cursor.to_list(length=1000)
        candidate_products = [Product(**d) for d in docs]

    return evaluate_recommendations(requirements, candidate_products)


# 8. Provider Status & Configuration
@router.get(
    "/provider-status",
    response_model=ProviderStatusResponse,
    dependencies=[Depends(require_admin_user)],
    summary="Get sanitized provider configuration, models and fallback state",
)
async def get_provider_status_endpoint():
    s = get_settings()
    return ProviderStatusResponse(
        primary_llm=s.llm_provider,
        primary_model=s.groq_model if s.llm_provider == "groq" else (s.gemini_model if s.llm_provider == "gemini" else s.ollama_model),
        fallback_llm=s.llm_fallback_provider if s.llm_fallback_enabled else None,
        fallback_enabled=s.llm_fallback_enabled,
        stt_provider=s.stt_provider,
        stt_model=s.groq_whisper_model,
        tts_provider=s.tts_provider,
        tts_model=s.gemini_tts_model if s.tts_provider == "gemini" else s.groq_tts_model,
        environment=s.app_env,
        budget_mode="₹0 Prototype (Free tier / local only)",
    )


# 9. Audit Logs
@router.get(
    "/audit-logs",
    dependencies=[Depends(require_admin_user)],
    summary="List recent administrative audit logs",
)
async def get_audit_logs_endpoint(
    limit: int = Query(default=100, le=500),
    action: str | None = Query(default=None),
    database: Any = Depends(get_database),
):
    return await list_audit_events(database, limit=limit, action=action)


# 10. Support & Customer Conversations
@router.get(
    "/support/conversations",
    response_model=list[AdminConversationResponse],
    dependencies=[Depends(require_admin_user)],
    summary="List consultations for administrative support and compliance auditing",
)
async def list_support_conversations(
    company_id: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    database: Any = Depends(get_database),
):
    query: dict[str, Any] = {}
    if company_id:
        cid = parse_object_id(company_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID")
        query["company_id"] = cid

    cursor = database.conversations.find(query).sort("updated_at", -1).limit(limit)
    conv_docs = await cursor.to_list(length=limit)

    comp_docs = await database.companies.find().to_list(length=1000)
    company_map = {str(c["_id"]): c["name"] for c in comp_docs}

    user_docs = await database.users.find().to_list(length=1000)
    user_map = {str(u["_id"]): u["email"] for u in user_docs}

    results: list[AdminConversationResponse] = []
    for c in conv_docs:
        cid_str = str(c["company_id"])
        uid_str = str(c["user_id"])
        c_at = c.get("created_at", utc_now())
        u_at = c.get("updated_at", utc_now())

        results.append(
            AdminConversationResponse(
                id=str(c["_id"]),
                company_id=cid_str,
                company_name=company_map.get(cid_str, "Unknown"),
                user_id=uid_str,
                user_email=user_map.get(uid_str, "Unknown"),
                title=c.get("title") or "Technical Consultation",
                message_count=len(c.get("messages", [])),
                status=c.get("status", "active"),
                created_at=c_at.isoformat() if hasattr(c_at, "isoformat") else str(c_at),
                updated_at=u_at.isoformat() if hasattr(u_at, "isoformat") else str(u_at),
            )
        )
    return results


@router.get(
    "/support/conversations/{conversation_id}",
    response_model=AdminConversationDetailResponse,
    dependencies=[Depends(require_admin_user)],
    summary="Inspect consultation message history for authorized technical support",
)
async def get_support_conversation_detail(
    conversation_id: str,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    conv_id = parse_object_id(conversation_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid conversation ID")
    conv = await database.conversations.find_one({"_id": conv_id})
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    comp = await database.companies.find_one({"_id": conv["company_id"]})
    comp_name = comp["name"] if comp else "Unknown"

    usr = await database.users.find_one({"_id": conv["user_id"]})
    user_email = usr["email"] if usr else "Unknown"

    c_at = conv.get("created_at", utc_now())
    u_at = conv.get("updated_at", utc_now())

    raw_msgs = conv.get("messages", [])
    formatted_msgs = []
    for m in raw_msgs:
        m_at = m.get("created_at", utc_now())
        formatted_msgs.append({
            "id": m.get("id"),
            "role": m.get("role"),
            "content": m.get("content"),
            "input_modality": m.get("input_modality", "text"),
            "language": m.get("language"),
            "created_at": m_at.isoformat() if hasattr(m_at, "isoformat") else str(m_at),
        })

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="INSPECT_CONVERSATION",
        target_type="conversation",
        target_id=conversation_id,
        details=f"Admin inspected conversation '{conv.get('title')}' for support",
    )

    return AdminConversationDetailResponse(
        id=str(conv["_id"]),
        company_id=str(conv["company_id"]),
        company_name=comp_name,
        user_id=str(conv["user_id"]),
        user_email=user_email,
        title=conv.get("title") or "Technical Consultation",
        status=conv.get("status", "active"),
        messages=formatted_msgs,
        created_at=c_at.isoformat() if hasattr(c_at, "isoformat") else str(c_at),
        updated_at=u_at.isoformat() if hasattr(u_at, "isoformat") else str(u_at),
    )


# --- 11. Leads & Inquiries Management ---

def _sanitize_csv_cell(value: Any) -> str:
    """Neutralizes formula injection characters (=, +, -, @, tab, cr) per OWASP guidelines."""
    if value is None:
        return ""
    val_str = str(value).strip()
    if val_str and val_str[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + val_str
    return val_str


def build_admin_lead_response(lead_doc: dict) -> LeadResponse:
    c_at = lead_doc.get("created_at", utc_now())
    u_at = lead_doc.get("updated_at", utc_now())
    f_at = lead_doc.get("preferred_follow_up_at")

    internal_notes = lead_doc.get("internal_notes")
    if internal_notes is None and lead_doc.get("follow_up_notes") and not lead_doc.get("preferred_follow_up_at"):
        internal_notes = lead_doc.get("follow_up_notes")

    cust_notes = lead_doc.get("notes")
    return LeadResponse(
        id=str(lead_doc["_id"]),
        customer_user_id=str(lead_doc["customer_user_id"]),
        company_id=str(lead_doc["company_id"]),
        conversation_id=str(lead_doc["conversation_id"]),
        customer_name=lead_doc.get("customer_name", "Unknown"),
        company_name=lead_doc.get("company_name", "Unknown"),
        email=str(lead_doc.get("email", "")),
        phone=lead_doc.get("phone"),
        industry=lead_doc.get("industry"),
        application=lead_doc.get("application"),
        fluid_description=lead_doc.get("fluid_description"),
        viscosity_cp=lead_doc.get("viscosity_cp"),
        viscosity_unit=lead_doc.get("viscosity_unit", "cP"),
        flow_rate_ml_min=lead_doc.get("flow_rate_ml_min"),
        flow_rate_unit=lead_doc.get("flow_rate_unit", "ml/min"),
        droplet_size_um=lead_doc.get("droplet_size_um"),
        droplet_size_unit=lead_doc.get("droplet_size_unit", "µm"),
        spray_pattern=lead_doc.get("spray_pattern"),
        feed_configuration=lead_doc.get("feed_configuration"),
        notes=cust_notes,
        technical_notes=cust_notes,
        internal_notes=internal_notes,
        recommended_product_ids=lead_doc.get("recommended_product_ids", []),
        recommendation_summary=lead_doc.get("recommendation_summary"),
        lead_source=lead_doc.get("lead_source", "customer_consultation"),
        stage=lead_doc.get("stage", LeadStage.NEW),
        preferred_follow_up_at=f_at.isoformat() if hasattr(f_at, "isoformat") else (str(f_at) if f_at else None),
        preferred_follow_up_timezone=lead_doc.get("preferred_follow_up_timezone"),
        follow_up_notes=lead_doc.get("follow_up_notes"),
        created_at=c_at.isoformat() if hasattr(c_at, "isoformat") else str(c_at),
        updated_at=u_at.isoformat() if hasattr(u_at, "isoformat") else str(u_at),
    )


@router.get(
    "/leads",
    response_model=list[LeadResponse],
    dependencies=[Depends(require_admin_user)],
    summary="List customer inquiry leads across companies",
)
async def list_admin_leads(
    company_id: str | None = Query(default=None),
    stage: LeadStage | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    database: Any = Depends(get_database),
):
    query: dict[str, Any] = {}
    if company_id:
        cid = parse_object_id(company_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID")
        query["company_id"] = cid
    if stage:
        query["stage"] = stage

    docs = await database.leads.find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
    return [build_admin_lead_response(d) for d in docs]


@router.get(
    "/leads/export/csv",
    dependencies=[Depends(require_admin_user)],
    summary="Export leads to CSV with formula injection protection",
)
async def export_leads_csv(
    company_id: str | None = Query(default=None),
    stage: LeadStage | None = Query(default=None),
    database: Any = Depends(get_database),
):
    query: dict[str, Any] = {}
    if company_id:
        cid = parse_object_id(company_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID")
        query["company_id"] = cid
    if stage:
        query["stage"] = stage

    docs = await database.leads.find(query).sort("created_at", -1).to_list(length=1000)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Lead ID",
        "Company Name",
        "Customer Name",
        "Email",
        "Phone",
        "Stage",
        "Application",
        "Fluid",
        "Viscosity (cP)",
        "Flow Rate (ml/min)",
        "Droplet Size (um)",
        "Recommended Products",
        "Customer Notes",
        "Internal Notes",
        "Follow-Up Date",
        "Follow-Up Notes",
        "Created At",
    ])

    for d in docs:
        c_at = d.get("created_at", utc_now())
        f_at = d.get("preferred_follow_up_at")
        writer.writerow([
            _sanitize_csv_cell(str(d["_id"])),
            _sanitize_csv_cell(d.get("company_name", "")),
            _sanitize_csv_cell(d.get("customer_name", "")),
            _sanitize_csv_cell(d.get("email", "")),
            _sanitize_csv_cell(d.get("phone", "")),
            _sanitize_csv_cell(d.get("stage", "new")),
            _sanitize_csv_cell(d.get("application", "")),
            _sanitize_csv_cell(d.get("fluid_description", "")),
            _sanitize_csv_cell(d.get("viscosity_cp", "")),
            _sanitize_csv_cell(d.get("flow_rate_ml_min", "")),
            _sanitize_csv_cell(d.get("droplet_size_um", "")),
            _sanitize_csv_cell(", ".join(d.get("recommended_product_ids", []))),
            _sanitize_csv_cell(d.get("notes", "")),
            _sanitize_csv_cell(d.get("internal_notes", "")),
            _sanitize_csv_cell(f_at.isoformat() if hasattr(f_at, "isoformat") else str(f_at) if f_at else ""),
            _sanitize_csv_cell(d.get("follow_up_notes", "")),
            _sanitize_csv_cell(c_at.isoformat() if hasattr(c_at, "isoformat") else str(c_at)),
        ])

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="wavenxd_leads_export.csv"'},
    )


@router.get(
    "/leads/{lead_id}",
    response_model=LeadResponse,
    dependencies=[Depends(require_admin_user)],
    summary="Get lead details",
)
async def get_admin_lead_detail(
    lead_id: str,
    database: Any = Depends(get_database),
):
    lid = parse_object_id(lead_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid lead ID")
    doc = await database.leads.find_one({"_id": lid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return build_admin_lead_response(doc)


@router.patch(
    "/leads/{lead_id}",
    response_model=LeadResponse,
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Update lead stage and review notes",
)
async def update_admin_lead_stage(
    lead_id: str,
    body: UpdateLeadStageRequest,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    lid = parse_object_id(lead_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid lead ID")
    doc = await database.leads.find_one({"_id": lid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    now = utc_now()
    updates: dict[str, Any] = {
        "updated_at": now,
    }
    if body.stage is not None:
        updates["stage"] = body.stage

    # Handle internal engineering & sales notes without overwriting customer notes or follow_up_notes
    notes_val = body.internal_notes if body.internal_notes is not None else body.notes
    if notes_val is not None:
        updates["internal_notes"] = notes_val.strip()

    await database.leads.update_one({"_id": lid}, {"$set": updates})
    updated_doc = await database.leads.find_one({"_id": lid})

    audit_details = []
    if body.stage is not None:
        audit_details.append(f"stage to '{body.stage}'")
    if notes_val is not None:
        audit_details.append("internal notes updated")
    details_str = f"Admin updated lead {', '.join(audit_details)}" if audit_details else "Admin updated lead"

    await record_audit_event(
        database=database,
        admin_user=current_admin,
        action="UPDATE_LEAD_STAGE",
        target_type="lead",
        target_id=lead_id,
        details=details_str,
    )

    return build_admin_lead_response(updated_doc)

