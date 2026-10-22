from pydantic import Field

from app.models.common import MongoModel


class Company(MongoModel):
    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True
    contact_email: str | None = None
    notes: str | None = None
