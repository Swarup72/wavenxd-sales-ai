import uuid
from datetime import datetime
from pydantic import BaseModel, Field

from app.domain.enums import ConversationStatus, MessageRole
from app.models.common import MongoModel, PyObjectId, utc_now
from app.models.recommendation import CustomerRequirements, RecommendationResult


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: MessageRole
    content: str = Field(min_length=1, max_length=5000)
    input_modality: str = Field(default="text")
    language: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class Conversation(MongoModel):
    company_id: PyObjectId
    user_id: PyObjectId
    status: ConversationStatus = ConversationStatus.ACTIVE
    title: str | None = Field(default=None, max_length=200)
    preferred_language: str = Field(default="en")
    requirements: CustomerRequirements = Field(default_factory=CustomerRequirements)
    unresolved_questions: list[str] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)


# --- API Request & Response Schemas ---

class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    initial_message: str | None = Field(default=None, max_length=5000)
    preferred_language: str = Field(default="en")


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    language: str | None = Field(default=None)


class MessageResponse(BaseModel):
    id: str
    role: MessageRole
    content: str
    input_modality: str = "text"
    language: str | None = None
    created_at: str


class ConversationSummaryResponse(BaseModel):
    id: str
    company_id: str
    user_id: str
    status: ConversationStatus
    title: str | None = None
    preferred_language: str = "en"
    message_count: int
    created_at: str
    updated_at: str


class ConversationDetailResponse(BaseModel):
    id: str
    company_id: str
    user_id: str
    status: ConversationStatus
    title: str | None = None
    preferred_language: str = "en"
    requirements: CustomerRequirements
    unresolved_questions: list[str]
    messages: list[MessageResponse]
    created_at: str
    updated_at: str


class SendMessageResponse(BaseModel):
    conversation_id: str
    user_message: MessageResponse
    assistant_message: MessageResponse
    updated_requirements: CustomerRequirements
    unresolved_questions: list[str]
    recommendation_result: RecommendationResult | None = None
