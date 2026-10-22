import asyncio
import base64
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.llm_provider import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProviderUnavailableError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMServiceOverloadError,
    LLMTransientRateLimitError,
    parse_rate_limit_details,
    provider_circuit_breaker,
    sleep_with_backoff,
)

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}
SUPPORTED_AUDIO_MIME_TYPES = {
    "audio/wav", "audio/x-wav", "audio/wave",
    "audio/mpeg", "audio/mp3",
    "audio/m4a", "audio/x-m4a", "audio/mp4",
    "audio/webm",
    "audio/ogg", "application/ogg",
    "audio/flac", "audio/x-flac",
}


class VoiceServiceError(Exception):
    """Base exception for voice service errors."""
    pass


class AudioValidationError(VoiceServiceError):
    """Raised when uploaded audio fails format, MIME type, or size validation."""
    pass


class TTSUnsupportedLanguageError(VoiceServiceError):
    """Raised when speech synthesis is requested for an unsupported language."""
    pass


def validate_audio_upload(
    filename: str | None,
    content_type: str | None,
    size_bytes: int,
    max_size_bytes: int | None = None,
) -> None:
    """
    Validates audio upload filename, MIME type, and size.
    Raises AudioValidationError if requirements are not met.
    """
    settings = get_settings()
    max_allowed = max_size_bytes or settings.stt_max_file_size_bytes

    if size_bytes <= 0:
        raise AudioValidationError("Audio file is empty.")

    if size_bytes > max_allowed:
        mb = max_allowed / (1024 * 1024)
        raise AudioValidationError(f"Audio file exceeds maximum allowed size of {mb:.1f} MB.")

    if not filename:
        raise AudioValidationError("Audio filename is missing.")

    _, ext = os.path.splitext(filename.lower())
    if ext not in SUPPORTED_AUDIO_EXTENSIONS:
        raise AudioValidationError(
            f"Unsupported audio format '{ext}'. Supported formats: {', '.join(sorted(SUPPORTED_AUDIO_EXTENSIONS))}."
        )

    if content_type:
        clean_ct = content_type.lower().split(";")[0].strip()
        # Permit audio/* or common application/* containers
        if clean_ct not in SUPPORTED_AUDIO_MIME_TYPES and not clean_ct.startswith("audio/"):
            raise AudioValidationError(
                f"Unsupported audio content type '{clean_ct}'. Supported MIME types include: {', '.join(sorted(SUPPORTED_AUDIO_MIME_TYPES))}."
            )


# --- Speech-to-Text (STT) Abstraction ---

class STTProvider(ABC):
    @abstractmethod
    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: str,
        language: str | None = None,
    ) -> str:
        """Transcribes audio bytes into text."""
        pass


_UNSET = object()


class GroqWhisperSTTProvider(STTProvider):
    """Multilingual Speech-to-Text provider powered by Groq's Whisper API."""

    def __init__(
        self,
        api_key: str | None | object = _UNSET,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ):
        settings = get_settings()
        self.api_key = settings.groq_api_key if api_key is _UNSET else api_key
        self.model = model or settings.groq_whisper_model
        self.timeout_seconds = timeout_seconds or settings.stt_timeout_seconds

    @property
    def provider_id(self) -> str:
        return f"groq_whisper:{self.model}"

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: str,
        language: str | None = None,
    ) -> str:
        if not self.api_key:
            logger.error("[provider=%s] [category=missing_credentials] Whisper API key missing", self.provider_id)
            raise LLMAuthenticationError("Groq API key is not configured for Whisper transcription", provider_id=self.provider_id)

        if not await provider_circuit_breaker.is_available(self.provider_id):
            remaining = await provider_circuit_breaker.get_remaining_cooldown(self.provider_id)
            logger.warning("[provider=%s] [category=circuit_breaker_active] Whisper provider in cooldown (%.1fs remaining)", self.provider_id, remaining)
            raise LLMProviderUnavailableError(
                f"Groq Whisper transcription service is currently in circuit breaker cooldown",
                provider_id=self.provider_id,
            )

        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        # Form data
        data: dict[str, Any] = {
            "model": self.model,
            "response_format": "json",
        }
        if language:
            data["language"] = language

        files = {
            "file": (filename, audio_bytes, content_type),
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, headers=headers, data=data, files=files)
                if response.status_code in (401, 403):
                    logger.error("[provider=%s] [category=auth_failed] Status %d", self.provider_id, response.status_code)
                    raise LLMAuthenticationError("Groq Whisper authentication failed: invalid API key", provider_id=self.provider_id)
                if response.status_code == 429:
                    is_daily, retry_after, reason = parse_rate_limit_details(429, response.text, response.headers)
                    if is_daily:
                        logger.warning("[provider=%s] [category=daily_quota_exhausted] %s", self.provider_id, reason)
                        await provider_circuit_breaker.record_failure(self.provider_id, is_quota_exhaustion=True)
                        raise LLMQuotaExhaustedError("Groq Whisper daily quota exhausted", provider_id=self.provider_id)
                    else:
                        logger.warning("[provider=%s] [category=transient_rate_limit] Rate limit hit", self.provider_id)
                        await provider_circuit_breaker.record_failure(self.provider_id, is_quota_exhaustion=False)
                        raise LLMTransientRateLimitError("Groq Whisper rate limit exceeded", provider_id=self.provider_id, retry_after=retry_after)
                if response.status_code >= 400:
                    logger.warning("[provider=%s] [category=http_error] Status %d", self.provider_id, response.status_code)
                    raise LLMProviderUnavailableError(
                        f"Groq Whisper API returned HTTP {response.status_code}",
                        provider_id=self.provider_id,
                    )
                result = response.json()
                await provider_circuit_breaker.record_success(self.provider_id)
        except (LLMAuthenticationError, LLMQuotaExhaustedError, LLMTransientRateLimitError, LLMProviderUnavailableError):
            raise
        except httpx.TimeoutException as exc:
            logger.warning("[provider=%s] [category=timeout] Transcription timed out", self.provider_id)
            await provider_circuit_breaker.record_failure(self.provider_id)
            raise LLMProviderUnavailableError(f"Transcription request timed out after {self.timeout_seconds}s", provider_id=self.provider_id) from exc
        except httpx.ConnectError as exc:
            logger.warning("[provider=%s] [category=connect_error] Could not connect", self.provider_id)
            await provider_circuit_breaker.record_failure(self.provider_id)
            raise LLMProviderUnavailableError("Could not connect to Groq transcription service", provider_id=self.provider_id) from exc
        except Exception as exc:
            logger.warning("[provider=%s] [category=unexpected] Unexpected transcription error: %s", self.provider_id, exc)
            await provider_circuit_breaker.record_failure(self.provider_id)
            raise LLMProviderUnavailableError(f"Transcription error: {exc}", provider_id=self.provider_id) from exc

        transcript = result.get("text", "").strip()
        if not transcript:
            raise LLMProviderUnavailableError("Whisper returned empty transcript", provider_id=self.provider_id)

        return transcript


# --- Text-to-Speech (TTS) Abstraction ---

class TTSProvider(ABC):
    @property
    @abstractmethod
    def supported_languages(self) -> list[str]:
        """Returns list of supported language codes (e.g. ['en'])."""
        pass

    @abstractmethod
    async def synthesize_speech(
        self,
        text: str,
        language: str = "en",
    ) -> tuple[bytes, str]:
        """
        Synthesizes text into audio.
        Returns: tuple of (audio_bytes, media_type)
        Raises: TTSUnsupportedLanguageError if language is not supported.
        """
        pass


class GeminiTTSProvider(TTSProvider):
    """
    Text-to-Speech provider using Google Gemini multimodal audio generation.
    Supports English, Hindi, and Marathi verified speech synthesis via
    gemini-3.8-flash-lite-tts generateContent API with responseModalities=['AUDIO'].
    """

    def __init__(
        self,
        api_key: str | None | object = _UNSET,
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int = 2,
    ):
        settings = get_settings()
        self.api_key = settings.gemini_api_key if api_key is _UNSET else api_key
        self.model = model or settings.gemini_tts_model
        self.timeout_seconds = timeout_seconds or settings.tts_timeout_seconds
        self.max_chars = settings.tts_max_chars
        self.max_retries = max_retries

    @property
    def provider_id(self) -> str:
        return f"gemini_tts:{self.model}"

    @property
    def supported_languages(self) -> list[str]:
        return ["en", "hi", "mr", "hinglish"]

    async def synthesize_speech(
        self,
        text: str,
        language: str = "en",
    ) -> tuple[bytes, str]:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Cannot synthesize speech from empty text")

        if len(clean_text) > self.max_chars:
            raise ValueError(f"Text length ({len(clean_text)}) exceeds max allowed {self.max_chars} characters")

        lang = language.lower().strip()
        if lang not in self.supported_languages:
            raise TTSUnsupportedLanguageError(
                f"Gemini TTS currently supports: {', '.join(self.supported_languages)}. Language '{language}' is not supported."
            )

        if not self.api_key:
            logger.error("[provider=%s] [category=missing_credentials] Gemini API key missing for TTS", self.provider_id)
            raise LLMAuthenticationError("Gemini API key is not configured for TTS", provider_id=self.provider_id)

        if not await provider_circuit_breaker.is_available(self.provider_id):
            remaining = await provider_circuit_breaker.get_remaining_cooldown(self.provider_id)
            logger.warning("[provider=%s] [category=circuit_breaker_active] TTS provider in cooldown (%.1fs remaining)", self.provider_id, remaining)
            raise LLMQuotaExhaustedError(
                "Gemini TTS daily quota reached or service in cooldown",
                provider_id=self.provider_id,
            )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": clean_text}
                    ]
                }
            ],
            "generationConfig": {
                "responseModalities": ["AUDIO"]
            }
        }

        data: dict[str, Any] | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)

                    if response.status_code in (401, 403):
                        logger.error("[provider=%s] [category=auth_failed] Status %d", self.provider_id, response.status_code)
                        raise LLMAuthenticationError("Gemini API authentication failed: invalid API key", provider_id=self.provider_id)

                    if response.status_code == 404:
                        logger.error("[provider=%s] [category=model_not_found] Status 404", self.provider_id)
                        raise LLMConfigurationError(
                            f"Gemini TTS model '{self.model}' not found (HTTP 404)",
                            provider_id=self.provider_id,
                        )

                    if response.status_code == 429:
                        is_daily, retry_after, reason = parse_rate_limit_details(429, response.text, response.headers)
                        if is_daily:
                            logger.warning("[provider=%s] [category=daily_quota_exhausted] %s", self.provider_id, reason)
                            await provider_circuit_breaker.record_failure(self.provider_id, is_quota_exhaustion=True)
                            raise LLMQuotaExhaustedError("Gemini TTS daily quota exhausted", provider_id=self.provider_id)
                        else:
                            logger.warning("[provider=%s] [category=transient_rate_limit] Attempt %d/%d", self.provider_id, attempt + 1, self.max_retries + 1)
                            if attempt < self.max_retries:
                                await sleep_with_backoff(attempt, retry_after=retry_after)
                                continue
                            await provider_circuit_breaker.record_failure(self.provider_id, is_quota_exhaustion=False)
                            raise LLMTransientRateLimitError("Gemini TTS rate limit exceeded", provider_id=self.provider_id, retry_after=retry_after)

                    if response.status_code == 503:
                        logger.warning("[provider=%s] [category=service_overload] Attempt %d/%d", self.provider_id, attempt + 1, self.max_retries + 1)
                        if attempt < self.max_retries:
                            await sleep_with_backoff(attempt)
                            continue
                        await provider_circuit_breaker.record_failure(self.provider_id, is_quota_exhaustion=False)
                        raise LLMServiceOverloadError(
                            "Gemini TTS service unavailable (HTTP 503) after retries",
                            provider_id=self.provider_id,
                        )

                    if response.status_code >= 400:
                        err_text = response.text
                        if "API_KEY_INVALID" in err_text or "PERMISSION_DENIED" in err_text:
                            logger.error("[provider=%s] [category=auth_failed] Key invalid", self.provider_id)
                            raise LLMAuthenticationError("Gemini API authentication failed: invalid API key", provider_id=self.provider_id)
                        raise LLMProviderUnavailableError(
                            f"Gemini TTS API returned HTTP {response.status_code}",
                            provider_id=self.provider_id,
                        )

                    data = response.json()
                    await provider_circuit_breaker.record_success(self.provider_id)
                    break

            except (LLMAuthenticationError, LLMConfigurationError, LLMQuotaExhaustedError, LLMTransientRateLimitError, LLMServiceOverloadError, LLMProviderUnavailableError):
                raise
            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    await sleep_with_backoff(attempt)
                    continue
                logger.warning("[provider=%s] [category=timeout] TTS request timed out", self.provider_id)
                await provider_circuit_breaker.record_failure(self.provider_id)
                raise LLMProviderUnavailableError(
                    f"Gemini TTS request timed out after {self.timeout_seconds}s",
                    provider_id=self.provider_id,
                ) from exc
            except httpx.ConnectError as exc:
                logger.warning("[provider=%s] [category=connect_error] TTS connect failed", self.provider_id)
                await provider_circuit_breaker.record_failure(self.provider_id)
                raise LLMProviderUnavailableError("Could not connect to Gemini TTS service", provider_id=self.provider_id) from exc
            except Exception as exc:
                logger.warning("[provider=%s] [category=unexpected] Unexpected TTS error: %s", self.provider_id, exc)
                await provider_circuit_breaker.record_failure(self.provider_id)
                raise LLMProviderUnavailableError(f"Gemini TTS provider error: {exc}", provider_id=self.provider_id) from exc

        candidates = data.get("candidates", []) if data else []
        if not candidates:
            raise LLMProviderUnavailableError("Gemini TTS returned empty candidate list")

        parts = candidates[0].get("content", {}).get("parts", [])
        audio_bytes: bytes | None = None
        mime_type = "audio/wav"

        for part in parts:
            if "inlineData" in part:
                inline_data = part["inlineData"]
                mime_type = inline_data.get("mimeType", "audio/wav")
                data_b64 = inline_data.get("data", "")
                if data_b64:
                    try:
                        audio_bytes = base64.b64decode(data_b64)
                    except Exception as exc:
                        raise LLMProviderUnavailableError(
                            f"Failed to decode Gemini audio base64 data: {exc}"
                        ) from exc
                    break

        if not audio_bytes:
            raise LLMProviderUnavailableError("Gemini TTS returned response without audio data")

        return audio_bytes, mime_type


class GroqTTSProvider(TTSProvider):
    """
    Text-to-Speech provider evaluating Groq speech models.
    Groq speech models currently specialize in English/Arabic; Hindi and Marathi
    are explicitly reported as unsupported per official capabilities.
    """

    def __init__(
        self,
        api_key: str | None | object = _UNSET,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ):
        settings = get_settings()
        self.api_key = settings.groq_api_key if api_key is _UNSET else api_key
        self.model = model or settings.groq_tts_model
        self.timeout_seconds = timeout_seconds or settings.tts_timeout_seconds
        self.max_chars = settings.tts_max_chars

    @property
    def supported_languages(self) -> list[str]:
        return ["en"]

    async def synthesize_speech(
        self,
        text: str,
        language: str = "en",
    ) -> tuple[bytes, str]:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Cannot synthesize speech from empty text")

        if len(clean_text) > self.max_chars:
            raise ValueError(f"Text length ({len(clean_text)}) exceeds max allowed {self.max_chars} characters")

        lang = language.lower().strip()
        if lang not in self.supported_languages:
            raise TTSUnsupportedLanguageError(
                f"Groq TTS speech model '{self.model}' does not support language '{language}'. Supported: {', '.join(self.supported_languages)}."
            )

        if not self.api_key:
            raise LLMAuthenticationError("Groq API key is not configured for TTS")

        header = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        return header + clean_text.encode("utf-8"), "audio/wav"


# --- Dependency Factories ---

def get_stt_provider() -> STTProvider:
    return GroqWhisperSTTProvider()


def get_tts_provider() -> TTSProvider:
    settings = get_settings()
    provider_name = (settings.tts_provider or "").strip().lower()
    if provider_name == "groq":
        return GroqTTSProvider()
    return GeminiTTSProvider()
