import asyncio
import json
import logging
import random
import re
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# --- Provider Exception Hierarchy ---

class LLMProviderError(Exception):
    """Base exception for all LLM provider errors."""
    def __init__(
        self,
        message: str,
        provider_id: str = "unknown",
        correlation_id: str | None = None,
    ):
        super().__init__(message)
        self.provider_id = provider_id
        self.correlation_id = correlation_id


class LLMProviderUnavailableError(LLMProviderError):
    """Raised when the LLM provider service is unreachable, times out, or unavailable."""
    pass


# Transient and specific error types subclass LLMProviderUnavailableError for clean backward compatibility
class LLMTransientError(LLMProviderUnavailableError):
    """Base exception for temporary, retryable, and fallback-eligible provider failures."""
    pass


class LLMServiceOverloadError(LLMProviderUnavailableError):
    """Raised when the LLM provider is overloaded (HTTP 503/502/504)."""
    pass


class LLMConfigurationError(LLMProviderUnavailableError):
    """Raised when model or provider configuration is invalid (e.g. HTTP 404). Non-retryable, NO fallback."""
    pass


class LLMTransientRateLimitError(LLMProviderUnavailableError):
    """Raised when a temporary rate limit (RPM/TPM burst) is hit."""
    def __init__(
        self,
        message: str,
        provider_id: str = "unknown",
        retry_after: float | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(message, provider_id=provider_id, correlation_id=correlation_id)
        self.retry_after = retry_after


# Backward compatibility alias
LLMRateLimitError = LLMTransientRateLimitError


class LLMQuotaExhaustedError(LLMProviderUnavailableError):
    """
    Raised when daily/hard quota is exhausted (RPD, TPD, or free-tier daily cap).
    Eligible for fallback to secondary provider, but bypasses retries on the exhausted model.
    """
    def __init__(
        self,
        message: str,
        provider_id: str = "unknown",
        cooldown_seconds: float = 1800.0,
        correlation_id: str | None = None,
    ):
        super().__init__(message, provider_id=provider_id, correlation_id=correlation_id)
        self.cooldown_seconds = cooldown_seconds


class LLMAuthenticationError(LLMProviderError):
    """Raised when credentials/API keys are invalid (HTTP 401/403). Non-retryable, NO fallback."""
    pass


# --- Rate Limit Parsing & Exponential Backoff Utilities ---

def parse_rate_limit_details(
    status_code: int,
    response_text: str,
    headers: httpx.Headers | dict[str, str] | None = None,
) -> tuple[bool, float | None, str]:
    """
    Parses rate limit responses (HTTP 429) to determine:
    1. is_daily_quota: True if daily / hard free tier limits are exhausted.
    2. retry_after: seconds to wait from Retry-After headers or body details.
    3. sanitized_reason: safe message free of secret keys or internal data.
    """
    retry_after: float | None = None
    if headers:
        raw_header = None
        if hasattr(headers, "get"):
            raw_header = headers.get("retry-after") or headers.get("Retry-After")
        if raw_header:
            try:
                retry_after = float(raw_header)
            except (ValueError, TypeError):
                pass

    lower_text = response_text.lower()
    daily_quota_signals = (
        "per day",
        "requestsperday",
        "tokensperday",
        "generate_content_api_requests_per_day",
        "daily quota",
        "limit: 20",
        "free_tier_requests_per_day",
        "resource_exhausted",
        "quota exceeded",
    )
    is_daily_quota = any(sig in lower_text for sig in daily_quota_signals)

    if retry_after is None:
        m = re.search(r"try again in ([0-9]+(?:\.[0-9]+)?)s", lower_text)
        if m:
            try:
                retry_after = float(m.group(1))
            except ValueError:
                pass

    reason = "Daily quota exhausted" if is_daily_quota else "Rate limit threshold reached"
    return is_daily_quota, retry_after, reason


async def sleep_with_backoff(
    attempt: int,
    base_seconds: float = 0.5,
    max_seconds: float = 3.0,
    retry_after: float | None = None,
    jitter_factor: float = 0.2,
) -> None:
    """
    Sleeps using bounded exponential backoff with jitter, respecting Retry-After where available.
    """
    if retry_after is not None and retry_after > 0:
        sleep_duration = min(retry_after, max_seconds)
    else:
        sleep_duration = min(base_seconds * (2 ** attempt), max_seconds)
        jitter = random.uniform(-jitter_factor * sleep_duration, jitter_factor * sleep_duration)
        sleep_duration = max(0.1, sleep_duration + jitter)
    await asyncio.sleep(sleep_duration)


# --- In-Memory Quota & Provider Circuit Breaker ---

class ProviderCircuitBreaker:
    """
    In-memory, process-local circuit breaker for LLM and voice providers.
    Tracks consecutive transient failures and daily quota exhaustion to avoid
    repeatedly calling degraded or quota-exhausted models within the same process.

    Architectural Limitations:
    1. Process-local: In multi-worker ASGI deployments (Uvicorn multiple workers or multiple
       containers), each process holds its own memory state. Breaker trips are local to the process.
    2. Ephemeral lifecycle: Server restarts or worker recycling reset cooldown states.
    3. Suitable for zero-budget constraints without external caching dependencies like Redis.
    """

    def __init__(
        self,
        default_cooldown_seconds: float = 30.0,
        quota_cooldown_seconds: float = 1800.0,
        failure_threshold: int = 3,
    ):
        self._cooldown_until: dict[str, float] = {}
        self._failure_counts: dict[str, int] = {}
        self._default_cooldown = default_cooldown_seconds
        self._quota_cooldown = quota_cooldown_seconds
        self._failure_threshold = failure_threshold
        self._lock = asyncio.Lock()

    async def is_available(self, provider_id: str) -> bool:
        async with self._lock:
            now = time.monotonic()
            until = self._cooldown_until.get(provider_id, 0.0)
            if now < until:
                return False
            return True

    async def get_remaining_cooldown(self, provider_id: str) -> float:
        async with self._lock:
            now = time.monotonic()
            until = self._cooldown_until.get(provider_id, 0.0)
            return max(0.0, until - now)

    async def record_success(self, provider_id: str) -> None:
        async with self._lock:
            self._failure_counts[provider_id] = 0
            self._cooldown_until.pop(provider_id, None)

    async def record_failure(
        self,
        provider_id: str,
        is_quota_exhaustion: bool = False,
        cooldown_seconds: float | None = None,
    ) -> None:
        async with self._lock:
            now = time.monotonic()
            if is_quota_exhaustion:
                duration = cooldown_seconds if cooldown_seconds is not None else self._quota_cooldown
                self._cooldown_until[provider_id] = now + duration
                self._failure_counts[provider_id] = self._failure_threshold
                logger.warning(
                    "[provider=%s] [category=quota_cooldown_set] Circuit breaker cooldown set for %.1fs",
                    provider_id,
                    duration,
                )
                return

            current_count = self._failure_counts.get(provider_id, 0) + 1
            self._failure_counts[provider_id] = current_count
            if current_count >= self._failure_threshold:
                duration = cooldown_seconds if cooldown_seconds is not None else self._default_cooldown
                self._cooldown_until[provider_id] = now + duration
                logger.warning(
                    "[provider=%s] [category=consecutive_failures] Threshold %d reached; placed in cooldown for %.1fs",
                    provider_id,
                    current_count,
                    duration,
                )

    def reset_sync(self) -> None:
        """Synchronously clears all cooldown states."""
        self._cooldown_until.clear()
        self._failure_counts.clear()

    async def reset(self) -> None:
        """Resets all cooldown states; used in test suites."""
        async with self._lock:
            self.reset_sync()


provider_circuit_breaker = ProviderCircuitBreaker()


# --- Models & Abstract Provider ---

class LLMResponse(BaseModel):
    content: str
    model: str
    raw_response: dict[str, Any] = Field(default_factory=dict)


class LLMProvider(ABC):
    @property
    def provider_id(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    async def generate_chat_response(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        correlation_id: str | None = None,
    ) -> LLMResponse:
        """Generates a chat completion response from the underlying LLM."""
        pass


async def _invoke_provider_safely(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    system_prompt: str | None,
    correlation_id: str,
) -> LLMResponse:
    """Helper to invoke providers while supporting mock classes that do not accept correlation_id."""
    try:
        return await provider.generate_chat_response(
            messages=messages,
            system_prompt=system_prompt,
            correlation_id=correlation_id,
        )
    except TypeError:
        return await provider.generate_chat_response(
            messages=messages,
            system_prompt=system_prompt,
        )


# --- Provider Implementations ---

class OllamaProvider(LLMProvider):
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_tokens: int | None = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout_seconds = timeout_seconds or settings.ollama_timeout_seconds
        self.max_tokens = max_tokens or settings.ollama_max_tokens

    @property
    def provider_id(self) -> str:
        return f"ollama:{self.model}"

    async def generate_chat_response(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        correlation_id: str | None = None,
    ) -> LLMResponse:
        corr_id = correlation_id or uuid.uuid4().hex[:8]
        if not await provider_circuit_breaker.is_available(self.provider_id):
            logger.warning(
                "[provider=%s] [category=circuit_breaker_active] [corr=%s] Skipping Ollama provider in cooldown",
                self.provider_id,
                corr_id,
            )
            raise LLMProviderUnavailableError(
                f"Ollama provider {self.provider_id} is in circuit breaker cooldown",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            )

        chat_messages: list[dict[str, str]] = []
        if system_prompt:
            chat_messages.append({"role": "system", "content": system_prompt})
        chat_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": chat_messages,
            "stream": False,
            "options": {
                "num_predict": self.max_tokens,
            },
        }

        url = f"{self.base_url}/api/chat"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                await provider_circuit_breaker.record_success(self.provider_id)
        except httpx.TimeoutException as exc:
            logger.warning("[provider=%s] [category=timeout] [corr=%s] Request timed out", self.provider_id, corr_id)
            await provider_circuit_breaker.record_failure(self.provider_id)
            raise LLMProviderUnavailableError(
                f"Ollama request timed out after {self.timeout_seconds}s",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            ) from exc
        except httpx.ConnectError as exc:
            logger.warning("[provider=%s] [category=connect_error] [corr=%s] Could not connect", self.provider_id, corr_id)
            await provider_circuit_breaker.record_failure(self.provider_id)
            raise LLMProviderUnavailableError(
                f"Could not connect to Ollama service at {self.base_url}",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            ) from exc
        except Exception as exc:
            logger.warning("[provider=%s] [category=unexpected] [corr=%s] Ollama error", self.provider_id, corr_id)
            await provider_circuit_breaker.record_failure(self.provider_id)
            raise LLMProviderUnavailableError(
                f"Ollama provider error: {exc}",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            ) from exc

        content = data.get("message", {}).get("content", "").strip()
        if not content:
            raise LLMProviderUnavailableError(
                "Ollama provider returned empty response",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            )

        return LLMResponse(
            content=content,
            model=data.get("model", self.model),
            raw_response=data,
        )


_UNSET = object()


class GeminiProvider(LLMProvider):
    """Google Gemini LLM provider using direct REST API."""

    def __init__(
        self,
        api_key: str | None | object = _UNSET,
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_tokens: int | None = None,
        max_retries: int = 2,
    ):
        settings = get_settings()
        self.api_key = settings.gemini_api_key if api_key is _UNSET else api_key
        self.model = model or settings.gemini_model
        self.timeout_seconds = timeout_seconds or settings.gemini_timeout_seconds
        self.max_tokens = max_tokens or settings.ollama_max_tokens
        self.max_retries = max_retries

    @property
    def provider_id(self) -> str:
        return f"gemini:{self.model}"

    async def generate_chat_response(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        correlation_id: str | None = None,
    ) -> LLMResponse:
        corr_id = correlation_id or uuid.uuid4().hex[:8]

        if not self.api_key:
            logger.error("[provider=%s] [category=missing_credentials] [corr=%s] API key not configured", self.provider_id, corr_id)
            raise LLMAuthenticationError(
                "Gemini API key is not configured",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            )

        if not await provider_circuit_breaker.is_available(self.provider_id):
            remaining = await provider_circuit_breaker.get_remaining_cooldown(self.provider_id)
            logger.warning(
                "[provider=%s] [category=circuit_breaker_active] [corr=%s] Provider is in cooldown (%.1fs remaining)",
                self.provider_id,
                corr_id,
                remaining,
            )
            raise LLMProviderUnavailableError(
                f"Gemini provider {self.provider_id} is in circuit breaker cooldown",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            )

        contents: list[dict[str, Any]] = []
        for m in messages:
            role = "user" if m.get("role") == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": m.get("content", "")}]
            })

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": self.max_tokens,
            },
        }

        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        data: dict[str, Any] | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)

                    if response.status_code in (401, 403):
                        logger.error("[provider=%s] [category=auth_failed] [corr=%s] Status %d", self.provider_id, corr_id, response.status_code)
                        raise LLMAuthenticationError(
                            "Gemini API authentication failed: invalid API key",
                            provider_id=self.provider_id,
                            correlation_id=corr_id,
                        )

                    if response.status_code == 404:
                        logger.error("[provider=%s] [category=model_not_found] [corr=%s] Status 404", self.provider_id, corr_id)
                        raise LLMConfigurationError(
                            f"Gemini model '{self.model}' not found (HTTP 404): {response.text}",
                            provider_id=self.provider_id,
                            correlation_id=corr_id,
                        )

                    if response.status_code == 429:
                        is_daily, retry_after, reason = parse_rate_limit_details(429, response.text, response.headers)
                        if is_daily:
                            logger.warning(
                                "[provider=%s] [category=daily_quota_exhausted] [corr=%s] %s",
                                self.provider_id,
                                corr_id,
                                reason,
                            )
                            await provider_circuit_breaker.record_failure(self.provider_id, is_quota_exhaustion=True)
                            raise LLMQuotaExhaustedError(
                                f"Gemini daily quota exhausted: {reason}",
                                provider_id=self.provider_id,
                                correlation_id=corr_id,
                            )
                        else:
                            logger.warning(
                                "[provider=%s] [category=transient_rate_limit] [corr=%s] Attempt %d/%d",
                                self.provider_id,
                                corr_id,
                                attempt + 1,
                                self.max_retries + 1,
                            )
                            if attempt < self.max_retries:
                                await sleep_with_backoff(attempt, retry_after=retry_after)
                                continue
                            await provider_circuit_breaker.record_failure(self.provider_id, is_quota_exhaustion=False)
                            raise LLMTransientRateLimitError(
                                f"Gemini rate limit exceeded after retries: HTTP 429: {response.text}",
                                provider_id=self.provider_id,
                                retry_after=retry_after,
                                correlation_id=corr_id,
                            )

                    if response.status_code == 503:
                        logger.warning(
                            "[provider=%s] [category=service_overload] [corr=%s] Attempt %d/%d",
                            self.provider_id,
                            corr_id,
                            attempt + 1,
                            self.max_retries + 1,
                        )
                        if attempt < self.max_retries:
                            await sleep_with_backoff(attempt)
                            continue
                        await provider_circuit_breaker.record_failure(self.provider_id, is_quota_exhaustion=False)
                        raise LLMServiceOverloadError(
                            f"Gemini service unavailable (HTTP 503) after retries: {response.text}",
                            provider_id=self.provider_id,
                            correlation_id=corr_id,
                        )

                    if response.status_code >= 400:
                        err_msg = response.text
                        if "API_KEY_INVALID" in err_msg or "PERMISSION_DENIED" in err_msg:
                            logger.error("[provider=%s] [category=auth_failed] [corr=%s] Key rejected", self.provider_id, corr_id)
                            raise LLMAuthenticationError(
                                "Gemini API authentication failed: invalid API key",
                                provider_id=self.provider_id,
                                correlation_id=corr_id,
                            )
                        raise LLMProviderUnavailableError(
                            f"Gemini API returned HTTP {response.status_code}: {err_msg}",
                            provider_id=self.provider_id,
                            correlation_id=corr_id,
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
                logger.warning("[provider=%s] [category=timeout] [corr=%s] Timed out", self.provider_id, corr_id)
                await provider_circuit_breaker.record_failure(self.provider_id)
                raise LLMProviderUnavailableError(
                    f"Gemini request timed out after {self.timeout_seconds}s",
                    provider_id=self.provider_id,
                    correlation_id=corr_id,
                ) from exc
            except httpx.ConnectError as exc:
                logger.warning("[provider=%s] [category=connect_error] [corr=%s] Connection failed", self.provider_id, corr_id)
                await provider_circuit_breaker.record_failure(self.provider_id)
                raise LLMProviderUnavailableError(
                    "Could not connect to Gemini service",
                    provider_id=self.provider_id,
                    correlation_id=corr_id,
                ) from exc
            except Exception as exc:
                logger.warning("[provider=%s] [category=unexpected] [corr=%s] Provider error", self.provider_id, corr_id)
                await provider_circuit_breaker.record_failure(self.provider_id)
                raise LLMProviderUnavailableError(
                    f"Gemini provider error: {exc}",
                    provider_id=self.provider_id,
                    correlation_id=corr_id,
                ) from exc

        candidates = data.get("candidates", []) if data else []
        if not candidates:
            raise LLMProviderUnavailableError(
                "Gemini returned empty candidate list",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            )

        parts = candidates[0].get("content", {}).get("parts", [])
        content = "".join(p.get("text", "") for p in parts if "text" in p).strip()
        if not content:
            raise LLMProviderUnavailableError(
                "Gemini returned candidate without text parts",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            )

        return LLMResponse(
            content=content,
            model=self.model,
            raw_response=data,
        )


class GroqProvider(LLMProvider):
    """Groq Cloud LLM provider using OpenAI-compatible REST API."""

    def __init__(
        self,
        api_key: str | None | object = _UNSET,
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_tokens: int | None = None,
        max_retries: int = 2,
    ):
        settings = get_settings()
        self.api_key = settings.groq_api_key if api_key is _UNSET else api_key
        self.model = model or settings.groq_model
        self.timeout_seconds = timeout_seconds or settings.groq_timeout_seconds
        self.max_tokens = max_tokens or settings.ollama_max_tokens
        self.max_retries = max_retries

    @property
    def provider_id(self) -> str:
        return f"groq:{self.model}"

    async def generate_chat_response(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        correlation_id: str | None = None,
    ) -> LLMResponse:
        corr_id = correlation_id or uuid.uuid4().hex[:8]

        if not self.api_key:
            logger.error("[provider=%s] [category=missing_credentials] [corr=%s] API key not configured", self.provider_id, corr_id)
            raise LLMAuthenticationError(
                "Groq API key is not configured",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            )

        if not await provider_circuit_breaker.is_available(self.provider_id):
            remaining = await provider_circuit_breaker.get_remaining_cooldown(self.provider_id)
            logger.warning(
                "[provider=%s] [category=circuit_breaker_active] [corr=%s] Provider is in cooldown (%.1fs remaining)",
                self.provider_id,
                corr_id,
                remaining,
            )
            raise LLMProviderUnavailableError(
                f"Groq provider {self.provider_id} is in circuit breaker cooldown",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            )

        chat_messages: list[dict[str, str]] = []
        if system_prompt:
            chat_messages.append({"role": "system", "content": system_prompt})
        chat_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": chat_messages,
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
        }

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        data: dict[str, Any] | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)

                    if response.status_code in (401, 403):
                        logger.error("[provider=%s] [category=auth_failed] [corr=%s] Status %d", self.provider_id, corr_id, response.status_code)
                        raise LLMAuthenticationError(
                            "Groq API authentication failed: invalid API key",
                            provider_id=self.provider_id,
                            correlation_id=corr_id,
                        )

                    if response.status_code == 404:
                        logger.error("[provider=%s] [category=model_not_found] [corr=%s] Status 404", self.provider_id, corr_id)
                        raise LLMConfigurationError(
                            f"Groq model '{self.model}' not found (HTTP 404)",
                            provider_id=self.provider_id,
                            correlation_id=corr_id,
                        )

                    if response.status_code == 429:
                        is_daily, retry_after, reason = parse_rate_limit_details(429, response.text, response.headers)
                        if is_daily:
                            logger.warning(
                                "[provider=%s] [category=daily_quota_exhausted] [corr=%s] %s",
                                self.provider_id,
                                corr_id,
                                reason,
                            )
                            await provider_circuit_breaker.record_failure(self.provider_id, is_quota_exhaustion=True)
                            raise LLMQuotaExhaustedError(
                                f"Groq daily quota exhausted: {reason}",
                                provider_id=self.provider_id,
                                correlation_id=corr_id,
                            )
                        else:
                            logger.warning(
                                "[provider=%s] [category=transient_rate_limit] [corr=%s] Attempt %d/%d",
                                self.provider_id,
                                corr_id,
                                attempt + 1,
                                self.max_retries + 1,
                            )
                            if attempt < self.max_retries:
                                await sleep_with_backoff(attempt, retry_after=retry_after)
                                continue
                            await provider_circuit_breaker.record_failure(self.provider_id, is_quota_exhaustion=False)
                            raise LLMTransientRateLimitError(
                                "Groq API rate limit exceeded after retries",
                                provider_id=self.provider_id,
                                retry_after=retry_after,
                                correlation_id=corr_id,
                            )

                    if response.status_code == 503:
                        logger.warning(
                            "[provider=%s] [category=service_overload] [corr=%s] Attempt %d/%d",
                            self.provider_id,
                            corr_id,
                            attempt + 1,
                            self.max_retries + 1,
                        )
                        if attempt < self.max_retries:
                            await sleep_with_backoff(attempt)
                            continue
                        await provider_circuit_breaker.record_failure(self.provider_id, is_quota_exhaustion=False)
                        raise LLMServiceOverloadError(
                            "Groq service unavailable (HTTP 503) after retries",
                            provider_id=self.provider_id,
                            correlation_id=corr_id,
                        )

                    if response.status_code >= 400:
                        raise LLMProviderUnavailableError(
                            f"Groq API returned HTTP {response.status_code}",
                            provider_id=self.provider_id,
                            correlation_id=corr_id,
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
                logger.warning("[provider=%s] [category=timeout] [corr=%s] Timed out", self.provider_id, corr_id)
                await provider_circuit_breaker.record_failure(self.provider_id)
                raise LLMProviderUnavailableError(
                    f"Groq request timed out after {self.timeout_seconds}s",
                    provider_id=self.provider_id,
                    correlation_id=corr_id,
                ) from exc
            except httpx.ConnectError as exc:
                logger.warning("[provider=%s] [category=connect_error] [corr=%s] Connection failed", self.provider_id, corr_id)
                await provider_circuit_breaker.record_failure(self.provider_id)
                raise LLMProviderUnavailableError(
                    "Could not connect to Groq service",
                    provider_id=self.provider_id,
                    correlation_id=corr_id,
                ) from exc
            except Exception as exc:
                logger.warning("[provider=%s] [category=unexpected] [corr=%s] Provider error", self.provider_id, corr_id)
                await provider_circuit_breaker.record_failure(self.provider_id)
                raise LLMProviderUnavailableError(
                    f"Groq provider error: {exc}",
                    provider_id=self.provider_id,
                    correlation_id=corr_id,
                ) from exc

        choices = data.get("choices", []) if data else []
        if not choices:
            raise LLMProviderUnavailableError(
                "Groq returned empty choices list",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            )

        content = choices[0].get("message", {}).get("content", "").strip()
        if not content:
            raise LLMProviderUnavailableError(
                "Groq returned empty message content",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            )

        return LLMResponse(
            content=content,
            model=data.get("model", self.model),
            raw_response=data,
        )


class FallbackLLMProvider(LLMProvider):
    """
    Production-style quota-aware fallback wrapper for LLM providers.
    Attempts configured primary provider first.
    On eligible transient failures or rate limits/exhausted daily quota, attempts
    the configured secondary provider at most once.
    
    Non-retryable errors (authentication failures, invalid configuration/models)
    fail immediately without attempting fallback.
    """

    def __init__(self, primary: LLMProvider, fallback: LLMProvider):
        self.primary = primary
        self.fallback = fallback

    @property
    def provider_id(self) -> str:
        p_id = getattr(self.primary, "provider_id", self.primary.__class__.__name__)
        f_id = getattr(self.fallback, "provider_id", self.fallback.__class__.__name__)
        return f"fallback({p_id}->{f_id})"

    async def generate_chat_response(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        correlation_id: str | None = None,
    ) -> LLMResponse:
        corr_id = correlation_id or uuid.uuid4().hex[:8]
        p_id = getattr(self.primary, "provider_id", self.primary.__class__.__name__)
        f_id = getattr(self.fallback, "provider_id", self.fallback.__class__.__name__)

        primary_available = await provider_circuit_breaker.is_available(p_id)
        if primary_available:
            try:
                return await _invoke_provider_safely(
                    provider=self.primary,
                    messages=messages,
                    system_prompt=system_prompt,
                    correlation_id=corr_id,
                )
            except (LLMAuthenticationError, LLMConfigurationError) as non_retryable:
                logger.error(
                    "[provider=%s] [category=non_retryable_error] [corr=%s] Primary failed with %s; fallback prohibited",
                    p_id,
                    corr_id,
                    non_retryable.__class__.__name__,
                )
                raise
            except (LLMProviderUnavailableError, LLMQuotaExhaustedError) as eligible_exc:
                logger.warning(
                    "[provider=%s] [category=fallback_triggered] [corr=%s] Primary failed (%s: %s). Attempting secondary %s at most once",
                    p_id,
                    corr_id,
                    eligible_exc.__class__.__name__,
                    str(eligible_exc),
                    f_id,
                )
        else:
            logger.warning(
                "[provider=%s] [category=circuit_breaker_bypassed] [corr=%s] Primary in cooldown; routing directly to secondary %s",
                p_id,
                corr_id,
                f_id,
            )

        # Attempt secondary provider at most once
        try:
            return await _invoke_provider_safely(
                provider=self.fallback,
                messages=messages,
                system_prompt=system_prompt,
                correlation_id=corr_id,
            )
        except Exception as sec_exc:
            logger.error(
                "[provider=%s] [category=all_providers_failed] [corr=%s] Secondary failed (%s: %s). All providers exhausted.",
                f_id,
                corr_id,
                sec_exc.__class__.__name__,
                str(sec_exc),
            )
            raise LLMProviderUnavailableError(
                f"All configured AI sales assistant providers failed. Last error: {sec_exc}",
                provider_id=self.provider_id,
                correlation_id=corr_id,
            ) from sec_exc


def create_provider_by_name(provider_name: str) -> LLMProvider:
    name = (provider_name or "").strip().lower()
    if name == "gemini":
        return GeminiProvider()
    elif name == "groq":
        return GroqProvider()
    elif name == "ollama":
        return OllamaProvider()
    else:
        logger.warning("Unknown LLM provider '%s', defaulting to OllamaProvider", name)
        return OllamaProvider()


def get_llm_provider() -> LLMProvider:
    """Dependency provider factory for FastAPI endpoints."""
    settings = get_settings()
    primary = create_provider_by_name(settings.llm_provider)

    if settings.llm_fallback_enabled and settings.llm_fallback_provider:
        fallback = create_provider_by_name(settings.llm_fallback_provider)
        return FallbackLLMProvider(primary=primary, fallback=fallback)

    return primary
