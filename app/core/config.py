from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "WaveNxD AI Sales Representative"
    app_env: str = "development"
    mongodb_uri: str = "mongodb://127.0.0.1:27017"
    mongodb_database: str = "wavenxd_sales"

    # Session & Cookie settings
    session_cookie_name: str = "wavenxd_session"
    session_cookie_secure: bool | None = None
    session_cookie_samesite: str = "lax"
    session_cookie_httponly: bool = True
    session_max_age_seconds: int = 60 * 60 * 24 * 7  # 7 days

    # CSRF & Security settings
    csrf_cookie_name: str = "wavenxd_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    invitation_expiry_hours: int = 48

    # Database Initialization & Demo Seeds
    auto_seed_demo_data: bool = True
    initial_admin_email: str = "admin@wavenxd.com"
    initial_admin_password: str = "ValidAdminPass123!"
    initial_customer_password: str = "ValidCustPass123!"

    # LLM & Conversation settings
    llm_provider: str = "groq"  # "ollama" | "gemini" | "groq"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3"
    ollama_timeout_seconds: float = 30.0
    ollama_max_tokens: int = 1000

    # Gemini settings
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_timeout_seconds: float = 30.0

    # Groq settings
    groq_api_key: str | None = None
    groq_model: str = "qwen/qwen3.8-27b"
    groq_timeout_seconds: float = 30.0

    # Explicit Fallback settings
    llm_fallback_enabled: bool = True
    llm_fallback_provider: str | None = "gemini"  # "gemini" | "groq" | "ollama"

    # Conversation limits
    conversation_max_messages: int = 100
    message_max_length: int = 5000

    # Voice Input (STT) settings
    stt_provider: str = "groq"  # "groq"
    groq_whisper_model: str = "whisper-large-v3"
    stt_timeout_seconds: float = 30.0
    stt_max_file_size_bytes: int = 25 * 1024 * 1024  # 25 MB

    # Voice Output (TTS) settings
    tts_provider: str = "gemini"  # "gemini" | "groq"
    gemini_tts_model: str = "gemini-3.8-flash-lite-tts"
    groq_tts_model: str = "playht-large"
    tts_timeout_seconds: float = 30.0
    tts_max_chars: int = 2000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

