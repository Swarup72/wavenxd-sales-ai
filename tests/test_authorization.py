from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.domain.enums import AccessRequestStatus, ProductStatus, UserRole
from app.models.product import Product
from app.models.user import User
from app.services.authorization import (
    approve_access_request,
    assign_product_to_company,
    create_customer_access_request,
    deactivate_product_assignment,
    get_verified_product_for_user,
    list_accessible_products_for_user,
    parse_object_id,
    reject_access_request,
)


class MockCursor:
    def __init__(self, items):
        self._items = list(items)

    def sort(self, key, direction=1):
        reverse = direction == -1
        self._items.sort(key=lambda x: x.get(key, 0), reverse=reverse)
        return self

    async def to_list(self, length=None):
        if length is not None:
            return self._items[:length]
        return self._items


class MockAuthzDB:
    def __init__(self):
        self.companies_data: dict[ObjectId, dict] = {}
        self.products_data: dict[ObjectId, dict] = {}
        self.assignments_data: dict[tuple[ObjectId, ObjectId], dict] = {}
        self.access_requests_data: dict[ObjectId, dict] = {}

    @property
    def companies(self):
        col = MagicMock()

        async def find_one(filter_dict):
            cid = filter_dict.get("_id")
            comp = self.companies_data.get(cid)
            if not comp:
                return None
            if "is_active" in filter_dict and comp.get("is_active") != filter_dict["is_active"]:
                return None
            return comp

        def find(filter_dict=None):
            filter_dict = filter_dict or {}
            items = []
            for c in self.companies_data.values():
                if "is_active" in filter_dict and c.get("is_active") != filter_dict["is_active"]:
                    continue
                items.append(c)
            return MockCursor(items)

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = MagicMock(side_effect=find)
        return col

    @property
    def products(self):
        col = MagicMock()

        async def find_one(filter_dict):
            pid = filter_dict.get("_id")
            prod = self.products_data.get(pid)
            if not prod:
                return None
            if "status" in filter_dict and prod.get("status") != filter_dict["status"]:
                return None
            if filter_dict.get("technical_review_required") is False and prod.get("technical_review_required", False):
                return None
            return prod

        def find(filter_dict=None):
            filter_dict = filter_dict or {}
            items = []
            for p in self.products_data.values():
                if "_id" in filter_dict and isinstance(filter_dict["_id"], dict) and "$in" in filter_dict["_id"]:
                    if p["_id"] not in filter_dict["_id"]["$in"]:
                        continue
                if "status" in filter_dict and p.get("status") != filter_dict["status"]:
                    continue
                if filter_dict.get("technical_review_required") is False and p.get("technical_review_required", False):
                    continue
                items.append(p)
            return MockCursor(items)

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = MagicMock(side_effect=find)
        return col

    @property
    def customer_product_assignments(self):
        col = MagicMock()

        async def find_one(filter_dict):
            cid = filter_dict.get("company_id")
            pid = filter_dict.get("product_id")
            assign = self.assignments_data.get((cid, pid))
            if not assign:
                return None
            if "is_active" in filter_dict and assign.get("is_active") != filter_dict["is_active"]:
                return None
            return assign

        def find(filter_dict=None):
            filter_dict = filter_dict or {}
            items = []
            for (cid, pid), a in self.assignments_data.items():
                if "company_id" in filter_dict and cid != filter_dict["company_id"]:
                    continue
                if "product_id" in filter_dict and pid != filter_dict["product_id"]:
                    continue
                if "is_active" in filter_dict and a.get("is_active") != filter_dict["is_active"]:
                    continue
                items.append(a)
            return MockCursor(items)

        async def update_one(filter_dict, update_dict, upsert=False):
            cid = filter_dict.get("company_id")
            pid = filter_dict.get("product_id")
            key = (cid, pid)
            if key not in self.assignments_data and upsert:
                self.assignments_data[key] = {
                    "_id": ObjectId(),
                    "company_id": cid,
                    "product_id": pid,
                    "is_active": True,
                    "assigned_by_user_id": ObjectId(),
                }
            assign = self.assignments_data.get(key)
            if assign:
                if "is_active" in filter_dict and assign.get("is_active") != filter_dict["is_active"]:
                    return MagicMock(modified_count=0)
                for k, v in update_dict.get("$set", {}).items():
                    assign[k] = v
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = MagicMock(side_effect=find)
        col.update_one = AsyncMock(side_effect=update_one)
        return col

    @property
    def access_requests(self):
        col = MagicMock()

        async def find_one(filter_dict):
            rid = filter_dict.get("_id")
            if rid:
                req = self.access_requests_data.get(rid)
                if req:
                    if "status" in filter_dict and req.get("status") != filter_dict["status"]:
                        return None
                    return req
                return None
            for req in self.access_requests_data.values():
                match = True
                for k, v in filter_dict.items():
                    if req.get(k) != v:
                        match = False
                        break
                if match:
                    return req
            return None

        def find(filter_dict=None):
            filter_dict = filter_dict or {}
            items = []
            for req in self.access_requests_data.values():
                match = True
                for k, v in filter_dict.items():
                    if req.get(k) != v:
                        match = False
                        break
                if match:
                    items.append(req)
            return MockCursor(items)

        async def insert_one(doc):
            d = dict(doc)
            d["_id"] = ObjectId()
            self.access_requests_data[d["_id"]] = d
            res = MagicMock()
            res.inserted_id = d["_id"]
            return res

        async def update_one(filter_dict, update_dict):
            rid = filter_dict.get("_id")
            req = self.access_requests_data.get(rid)
            if req:
                for k, v in update_dict.get("$set", {}).items():
                    req[k] = v
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        async def find_one_and_update(filter_dict, update_dict, return_document=None):
            rid = filter_dict.get("_id")
            req = self.access_requests_data.get(rid)
            if not req:
                return None
            if "status" in filter_dict and req.get("status") != filter_dict["status"]:
                return None
            for k, v in update_dict.get("$set", {}).items():
                req[k] = v
            return req

        col.find_one = AsyncMock(side_effect=find_one)
        col.find = MagicMock(side_effect=find)
        col.insert_one = AsyncMock(side_effect=insert_one)
        col.update_one = AsyncMock(side_effect=update_one)
        col.find_one_and_update = AsyncMock(side_effect=find_one_and_update)
        return col



@pytest.fixture
def authz_fixture():
    db = MockAuthzDB()

    company_a = ObjectId()
    company_b = ObjectId()

    db.companies_data[company_a] = {
        "_id": company_a,
        "name": "Company A",
        "is_active": True,
    }
    db.companies_data[company_b] = {
        "_id": company_b,
        "name": "Company B",
        "is_active": True,
    }


    admin_user = User(
        id=ObjectId(),
        email="admin@wavenxd.com",
        full_name="Admin User",
        role=UserRole.ADMIN,
        company_id=None,
    )

    customer_a = User(
        id=ObjectId(),
        email="customerA@companyA.com",
        full_name="Customer A",
        role=UserRole.CUSTOMER,
        company_id=company_a,
    )

    customer_b = User(
        id=ObjectId(),
        email="customerB@companyB.com",
        full_name="Customer B",
        role=UserRole.CUSTOMER,
        company_id=company_b,
    )

    # Products
    prod_published_a = ObjectId()
    prod_draft = ObjectId()
    prod_unassigned = ObjectId()

    db.products_data[prod_published_a] = {
        "_id": prod_published_a,
        "name": "Standard Nozzle 60kHz",
        "catalog_key": "standard-nozzle-60khz",
        "status": ProductStatus.PUBLISHED,
        "applications": ["Lab spray drying"],
    }

    db.products_data[prod_draft] = {
        "_id": prod_draft,
        "name": "180kHz Stent Nozzle",
        "catalog_key": "standard-nozzle-torch-180khz",
        "status": ProductStatus.DRAFT,
        "technical_review_required": True,
        "applications": ["Stent coatings"],
    }

    db.products_data[prod_unassigned] = {
        "_id": prod_unassigned,
        "name": "High-Flow Conical Nozzle",
        "catalog_key": "high-flow-conical-60khz",
        "status": ProductStatus.PUBLISHED,
        "applications": ["Industrial spray drying"],
    }

    # Company A is assigned prod_published_a and prod_draft
    db.assignments_data[(company_a, prod_published_a)] = {
        "_id": ObjectId(),
        "company_id": company_a,
        "product_id": prod_published_a,
        "is_active": True,
    }

    db.assignments_data[(company_a, prod_draft)] = {
        "_id": ObjectId(),
        "company_id": company_a,
        "product_id": prod_draft,
        "is_active": True,
    }

    return {
        "db": db,
        "company_a": company_a,
        "company_b": company_b,
        "admin_user": admin_user,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "prod_published_a": prod_published_a,
        "prod_draft": prod_draft,
        "prod_unassigned": prod_unassigned,
    }


@pytest.mark.anyio
async def test_admin_can_access_any_product(authz_fixture):
    db = authz_fixture["db"]
    admin = authz_fixture["admin_user"]

    # Admin can access published, draft, or unassigned product
    prod1 = await get_verified_product_for_user(db, admin, authz_fixture["prod_published_a"])
    assert prod1.name == "Standard Nozzle 60kHz"

    prod2 = await get_verified_product_for_user(db, admin, authz_fixture["prod_draft"])
    assert prod2.name == "180kHz Stent Nozzle"

    prod3 = await get_verified_product_for_user(db, admin, authz_fixture["prod_unassigned"])
    assert prod3.name == "High-Flow Conical Nozzle"


@pytest.mark.anyio
async def test_customer_can_access_assigned_published_product(authz_fixture):
    db = authz_fixture["db"]
    customer_a = authz_fixture["customer_a"]

    prod = await get_verified_product_for_user(db, customer_a, authz_fixture["prod_published_a"])
    assert prod.name == "Standard Nozzle 60kHz"
    assert prod.status == ProductStatus.PUBLISHED


@pytest.mark.anyio
async def test_customer_cannot_access_unassigned_product(authz_fixture):
    db = authz_fixture["db"]
    customer_a = authz_fixture["customer_a"]

    # Product exists in catalog, but is not assigned to Company A -> raises 404
    with pytest.raises(HTTPException) as exc_info:
        await get_verified_product_for_user(db, customer_a, authz_fixture["prod_unassigned"])

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Product not found"


@pytest.mark.anyio
async def test_customer_cannot_access_draft_product_even_if_assigned(authz_fixture):
    db = authz_fixture["db"]
    customer_a = authz_fixture["customer_a"]

    # Product is assigned to Company A, but is in DRAFT status -> raises 404
    with pytest.raises(HTTPException) as exc_info:
        await get_verified_product_for_user(db, customer_a, authz_fixture["prod_draft"])

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Product not found"


@pytest.mark.anyio
async def test_nonexistent_and_inaccessible_products_return_identical_404(authz_fixture):
    db = authz_fixture["db"]
    customer_a = authz_fixture["customer_a"]

    # 1. Nonexistent ObjectId
    non_existent_id = ObjectId()
    with pytest.raises(HTTPException) as exc_nonexistent:
        await get_verified_product_for_user(db, customer_a, non_existent_id)

    # 2. Inaccessible unassigned product
    with pytest.raises(HTTPException) as exc_unassigned:
        await get_verified_product_for_user(db, customer_a, authz_fixture["prod_unassigned"])

    # Must be completely indistinguishable to prevent product catalog discovery
    assert exc_nonexistent.value.status_code == exc_unassigned.value.status_code == 404
    assert exc_nonexistent.value.detail == exc_unassigned.value.detail == "Product not found"


@pytest.mark.anyio
async def test_company_isolation_between_customers(authz_fixture):
    db = authz_fixture["db"]
    customer_b = authz_fixture["customer_b"]

    # Product assigned to Company A cannot be accessed by Company B -> returns 404
    with pytest.raises(HTTPException) as exc_info:
        await get_verified_product_for_user(db, customer_b, authz_fixture["prod_published_a"])

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Product not found"


@pytest.mark.anyio
async def test_access_request_requires_admin_approval(authz_fixture):
    db = authz_fixture["db"]
    admin = authz_fixture["admin_user"]
    customer_b = authz_fixture["customer_b"]
    product_id = authz_fixture["prod_unassigned"]

    # 1. Access request created
    req_id = ObjectId()
    db.access_requests_data[req_id] = {
        "_id": req_id,
        "company_id": authz_fixture["company_b"],
        "requested_by_user_id": customer_b.id,
        "product_id": product_id,
        "status": AccessRequestStatus.PENDING,
    }

    # Before approval, customer cannot access
    with pytest.raises(HTTPException):
        await get_verified_product_for_user(db, customer_b, product_id)

    # Non-admin cannot approve
    with pytest.raises(HTTPException) as non_admin_exc:
        await approve_access_request(db, customer_b, req_id)
    assert non_admin_exc.value.status_code == 403

    # Admin approves request
    assignment = await approve_access_request(
        db, admin, req_id, review_note="Approved for pilot evaluation"
    )
    assert assignment.is_active is True
    assert assignment.company_id == authz_fixture["company_b"]
    assert assignment.product_id == product_id

    # Now customer B can access product
    prod = await get_verified_product_for_user(db, customer_b, product_id)
    assert prod.name == "High-Flow Conical Nozzle"


@pytest.mark.anyio
async def test_list_accessible_products_for_user(authz_fixture):
    db = authz_fixture["db"]
    admin = authz_fixture["admin_user"]
    customer_a = authz_fixture["customer_a"]
    customer_b = authz_fixture["customer_b"]

    # Admin receives all products in the catalog
    admin_prods = await list_accessible_products_for_user(db, admin)
    assert len(admin_prods) == 3

    # Customer A has assigned: prod_published_a and prod_draft
    # Only published and verified product is returned (prod_draft is excluded)
    customer_a_prods = await list_accessible_products_for_user(db, customer_a)
    assert len(customer_a_prods) == 1
    assert customer_a_prods[0].id == authz_fixture["prod_published_a"]

    # Customer B has no assignments yet
    customer_b_prods = await list_accessible_products_for_user(db, customer_b)
    assert len(customer_b_prods) == 0


@pytest.mark.anyio
async def test_assign_and_deactivate_product_assignment(authz_fixture):
    db = authz_fixture["db"]
    admin = authz_fixture["admin_user"]
    customer_a = authz_fixture["customer_a"]
    company_b = authz_fixture["company_b"]
    product_unassigned = authz_fixture["prod_unassigned"]
    product_draft = authz_fixture["prod_draft"]

    # Non-admin cannot assign products
    with pytest.raises(HTTPException) as exc_non_admin:
        await assign_product_to_company(db, customer_a, company_b, product_unassigned)
    assert exc_non_admin.value.status_code == 403

    # Admin cannot assign draft/unreviewed products
    with pytest.raises(HTTPException) as exc_draft:
        await assign_product_to_company(db, admin, company_b, product_draft)
    assert exc_draft.value.status_code == 400
    assert "Only published products" in exc_draft.value.detail

    # Admin assigns published product
    assignment = await assign_product_to_company(db, admin, company_b, product_unassigned)
    assert assignment.is_active is True
    assert assignment.company_id == company_b
    assert assignment.product_id == product_unassigned

    # Idempotent assignment does not create duplicates
    assignment_duplicate = await assign_product_to_company(db, admin, company_b, product_unassigned)
    assert assignment_duplicate.is_active is True

    # Admin deactivates assignment
    deactivated = await deactivate_product_assignment(db, admin, company_b, product_unassigned)
    assert deactivated is True

    # Deactivating again raises 404
    with pytest.raises(HTTPException) as exc_deact:
        await deactivate_product_assignment(db, admin, company_b, product_unassigned)
    assert exc_deact.value.status_code == 404


@pytest.mark.anyio
async def test_create_customer_access_request(authz_fixture):
    db = authz_fixture["db"]
    admin = authz_fixture["admin_user"]
    customer_b = authz_fixture["customer_b"]
    product_unassigned = authz_fixture["prod_unassigned"]
    product_draft = authz_fixture["prod_draft"]

    # Admin cannot submit customer access requests
    with pytest.raises(HTTPException) as exc_admin:
        await create_customer_access_request(db, admin, product_unassigned)
    assert exc_admin.value.status_code == 403

    # Non-existent or draft products return identical 404 to avoid leaking catalog
    with pytest.raises(HTTPException) as exc_nonexistent:
        await create_customer_access_request(db, customer_b, ObjectId())
    assert exc_nonexistent.value.status_code == 404
    assert exc_nonexistent.value.detail == "Product not found"

    with pytest.raises(HTTPException) as exc_draft_req:
        await create_customer_access_request(db, customer_b, product_draft)
    assert exc_draft_req.value.status_code == 404
    assert exc_draft_req.value.detail == "Product not found"

    # Valid request creation
    req = await create_customer_access_request(
        db, customer_b, product_unassigned, reason="Interested in high-flow trial"
    )
    assert req.status == AccessRequestStatus.PENDING
    assert req.company_id == customer_b.company_id
    assert req.requested_by_user_id == customer_b.id
    assert req.product_id == product_unassigned

    # Repeated request while pending is rejected
    with pytest.raises(HTTPException) as exc_dup:
        await create_customer_access_request(db, customer_b, product_unassigned)
    assert exc_dup.value.status_code == 400
    assert "already pending" in exc_dup.value.detail


@pytest.mark.anyio
async def test_reject_access_request(authz_fixture):
    db = authz_fixture["db"]
    admin = authz_fixture["admin_user"]
    customer_b = authz_fixture["customer_b"]
    product_id = authz_fixture["prod_unassigned"]

    req_id = ObjectId()
    db.access_requests_data[req_id] = {
        "_id": req_id,
        "company_id": authz_fixture["company_b"],
        "requested_by_user_id": customer_b.id,
        "product_id": product_id,
        "status": AccessRequestStatus.PENDING,
    }

    # Non-admin cannot reject
    with pytest.raises(HTTPException) as exc_non_admin:
        await reject_access_request(db, customer_b, req_id)
    assert exc_non_admin.value.status_code == 403

    # Admin rejects
    rejected = await reject_access_request(
        db, admin, req_id, review_note="Out of current trial capacity"
    )
    assert rejected.status == AccessRequestStatus.REJECTED
    assert rejected.reviewed_by_user_id == admin.id
    assert rejected.review_note == "Out of current trial capacity"

    # No assignment was created
    assert (authz_fixture["company_b"], product_id) not in db.assignments_data

    # Repeated rejection or approval fails
    with pytest.raises(HTTPException) as exc_already_reviewed:
        await reject_access_request(db, admin, req_id)
    assert exc_already_reviewed.value.status_code == 400

    with pytest.raises(HTTPException) as exc_approve_after_reject:
        await approve_access_request(db, admin, req_id)
    assert exc_approve_after_reject.value.status_code == 400


def test_parse_object_id_validation():
    # Valid ObjectId string
    valid_str = str(ObjectId())
    oid = parse_object_id(valid_str)
    assert isinstance(oid, ObjectId)
    assert str(oid) == valid_str

    # Passing existing ObjectId instance
    assert parse_object_id(oid) is oid

    # Malformed strings raise controlled HTTPException
    with pytest.raises(HTTPException) as exc:
        parse_object_id("not-a-valid-oid", error_status=400, detail="Invalid ID")
    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid ID"

