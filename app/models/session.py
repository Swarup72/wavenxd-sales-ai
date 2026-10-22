from datetime import datetime

from pydantic import Field

from app.models.common import MongoModel, PyObjectId


class Session(MongoModel):
    session_token_hash: str = Field(min_length=64, max_length=64)
    user_id: PyObjectId
    expires_at: datetime
    is_revoked: bool = False
    csrf_token: str = Field(min_length=16, max_length=128)
    user_agent: str | None = None
    ip_address: str | None = None
