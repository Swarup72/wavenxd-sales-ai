import pytest
from app.services.llm_provider import provider_circuit_breaker


@pytest.fixture(autouse=True)
def reset_circuit_breaker_between_tests():
    """Ensures each test starts with a clean circuit breaker state."""
    provider_circuit_breaker.reset_sync()
    yield
    provider_circuit_breaker.reset_sync()
