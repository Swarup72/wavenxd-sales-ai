from datetime import datetime

from pydantic import EmailStr, Field

from app.domain.enums import InvitationStatus
from app.models.common import MongoModel, PyObjectId


class Invitation(MongoModel):
    invitation_token_hash: str = Field(min_length=64, max_length=64)
    email: EmailStr
    company_id: PyObjectId
    invited_by_user_id: PyObjectId
    status: InvitationStatus = InvitationStatus.PENDING
    expires_at: datetime
    consumed_at: datetime | None = None
    consumed_by_user_id: PyObjectId | None = None
