import pytest
from bson import ObjectId
from pydantic import ValidationError

from app.domain.enums import AccessRequestStatus, ProductStatus, UserRole
from app.models import (
    AccessRequest,
    Company,
    CustomerProductAssignment,
    Product,
    User,
)


def test_company_defaults():
    company = Company(name="Example Company")

    assert company.name == "Example Company"
    assert company.is_active is True
    assert company.id is None


def test_admin_does_not_belong_to_customer_company():
    admin = User(
        email="admin@example.com",
        full_name="WaveNxD Admin",
        role=UserRole.ADMIN,
    )

    assert admin.company_id is None


def test_customer_requires_company():
    with pytest.raises(ValidationError):
        User(
            email="customer@example.com",
            full_name="Customer User",
            role=UserRole.CUSTOMER,
        )


def test_admin_cannot_be_assigned_to_customer_company():
    with pytest.raises(ValidationError):
        User(
            email="admin@example.com",
            full_name="WaveNxD Admin",
            role=UserRole.ADMIN,
            company_id=ObjectId(),
        )


def test_product_keeps_unknown_specs_unknown():
    product = Product(name="Catalog item")

    assert product.frequency_khz is None
    assert product.droplet_size_um is None
    assert product.viscosity_max_cp is None
    assert product.status == ProductStatus.DRAFT


def test_product_normalizes_duplicate_applications():
    product = Product(
        name="Test product",
        applications=[" Stent coating ", "Stent coating", "Fuel cell coating"],
    )

    assert product.applications == ["Stent coating", "Fuel cell coating"]


def test_assignment_uses_object_ids():
    company_id = ObjectId()
    product_id = ObjectId()
    admin_id = ObjectId()

    assignment = CustomerProductAssignment(
        company_id=company_id,
        product_id=product_id,
        assigned_by_user_id=admin_id,
    )

    assert assignment.company_id == company_id
    assert assignment.product_id == product_id


def test_access_request_starts_pending():
    request = AccessRequest(
        company_id=ObjectId(),
        requested_by_user_id=ObjectId(),
        product_id=ObjectId(),
    )

    assert request.status == AccessRequestStatus.PENDING


def test_product_catalog_key_validation():
    # Valid catalog key
    product = Product(
        name="Valid Key Product",
        catalog_key="standard-nozzle-60khz",
        category="ultrasonic_nozzle",
        viscosity_description="below 50 cP",
    )
    assert product.catalog_key == "standard-nozzle-60khz"
    assert product.category == "ultrasonic_nozzle"
    assert product.viscosity_description == "below 50 cP"

    # Uppercase and whitespace are normalized
    product2 = Product(
        name="Key With Space",
        catalog_key="  Standard-Nozzle-60khz  ",
    )
    assert product2.catalog_key == "standard-nozzle-60khz"

    # Empty string is rejected
    with pytest.raises(ValidationError):
        Product(name="Empty Key", catalog_key="")

    # Invalid characters rejected
    with pytest.raises(ValidationError):
        Product(name="Invalid Key", catalog_key="invalid key with spaces")

    with pytest.raises(ValidationError):
        Product(name="Invalid Key", catalog_key="invalid_key@123")

