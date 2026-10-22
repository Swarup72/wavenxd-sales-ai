from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    CUSTOMER = "customer"


class ProductStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class AccessRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ProductMatchStatus(StrEnum):
    MATCH = "match"
    POTENTIAL_MATCH_NEEDS_CONFIRMATION = (
        "potential_match_needs_confirmation"
    )
    NO_MATCH = "no_match"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class LLMProviderType(StrEnum):
    OLLAMA = "ollama"
    GEMINI = "gemini"
    GROQ = "groq"


class SupportedLanguage(StrEnum):
    EN = "en"
    HI = "hi"
    MR = "mr"
    HINGLISH = "hinglish"


class InputModality(StrEnum):
    TEXT = "text"
    VOICE = "voice"


class STTProviderType(StrEnum):
    GROQ = "groq"


class TTSProviderType(StrEnum):
    GEMINI = "gemini"
    GROQ = "groq"


class LeadStage(StrEnum):
    NEW = "new"
    QUALIFIED = "qualified"
    QUOTE_DRAFT = "quote_draft"
    FOLLOW_UP_REQUESTED = "follow_up_requested"
    CLOSED = "closed"


class EmailDispatchStatus(StrEnum):
    PREVIEW = "preview"
    SIMULATED = "simulated"
    SENT = "sent"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


class FollowUpStatus(StrEnum):
    PREPARED = "prepared"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


