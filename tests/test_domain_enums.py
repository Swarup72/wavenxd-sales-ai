from app.domain.enums import (
    AccessRequestStatus,
    ProductMatchStatus,
    ProductStatus,
    UserRole,
)


def test_user_roles():
    assert UserRole.ADMIN == "admin"
    assert UserRole.CUSTOMER == "customer"


def test_product_status_values():
    assert ProductStatus.DRAFT == "draft"
    assert ProductStatus.PUBLISHED == "published"
    assert ProductStatus.ARCHIVED == "archived"


def test_access_request_status_values():
    assert AccessRequestStatus.PENDING == "pending"
    assert AccessRequestStatus.APPROVED == "approved"
    assert AccessRequestStatus.REJECTED == "rejected"


def test_product_match_status_values():
    assert (
        ProductMatchStatus.POTENTIAL_MATCH_NEEDS_CONFIRMATION
        == "potential_match_needs_confirmation"
    )
    assert (
        ProductMatchStatus.INSUFFICIENT_INFORMATION
        == "insufficient_information"
    )
