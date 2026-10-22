import re

from pydantic import Field, field_validator

from app.domain.enums import ProductStatus
from app.models.common import MongoModel

CATALOG_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class Product(MongoModel):
    catalog_key: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    spray_pattern: str | None = None
    feed_configuration: str | None = None

    frequency_khz: float | None = Field(default=None, gt=0)
    droplet_size_um: float | None = Field(default=None, gt=0)

    flow_rate_min_ml_min: float | None = Field(default=None, ge=0)
    flow_rate_max_ml_min: float | None = Field(default=None, gt=0)
    flow_rate_description: str | None = None

    viscosity_max_cp: float | None = Field(default=None, gt=0)
    viscosity_description: str | None = Field(default=None, max_length=200)

    applications: list[str] = Field(default_factory=list)
    status: ProductStatus = ProductStatus.DRAFT
    technical_review_required: bool = False
    catalog_notes: str | None = None

    @field_validator("catalog_key")
    @classmethod
    def validate_catalog_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("catalog_key cannot be empty")
        if not CATALOG_KEY_PATTERN.match(normalized):
            raise ValueError(
                "catalog_key must consist of lowercase alphanumeric words separated by hyphens"
            )
        return normalized

    @field_validator("applications")
    @classmethod
    def normalize_applications(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(
            value.strip() for value in values if value.strip()
        ))

