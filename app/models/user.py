from typing import Self

from pydantic import EmailStr, Field, model_validator

from app.domain.enums import UserRole
from app.models.common import MongoModel, PyObjectId


class User(MongoModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: UserRole
    company_id: PyObjectId | None = None
    is_active: bool = True
    password_hash: str | None = None
    must_change_password: bool = True

    @model_validator(mode="after")
    def validate_company_scope(self) -> Self:
        if self.role == UserRole.ADMIN and self.company_id is not None:
            raise ValueError("Admin users must not belong to a customer company")

        if self.role == UserRole.CUSTOMER and self.company_id is None:
            raise ValueError("Customer users must belong to exactly one company")

        return self
