from pydantic import Field

from app.domain.enums import AccessRequestStatus
from app.models.common import MongoModel, PyObjectId


class AccessRequest(MongoModel):
    company_id: PyObjectId
    requested_by_user_id: PyObjectId
    product_id: PyObjectId
    reason: str | None = Field(default=None, max_length=2000)
    status: AccessRequestStatus = AccessRequestStatus.PENDING
    reviewed_by_user_id: PyObjectId | None = None
    review_note: str | None = Field(default=None, max_length=2000)
