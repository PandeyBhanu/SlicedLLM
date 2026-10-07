import pytest

from app.providers.models import GenerationParams, LLMResponse, ProviderConfig, TokenUsage


def test_provider_config_creation():
    """Test ProviderConfig model creation."""
    config = ProviderConfig(
        base_url="http://localhost:11434",
        api_key="test-key",
        timeout=30.0,
        max_retries=3,
        retry_delay=1.0,
        max_concurrent_requests=10,
    )

    assert config.base_url == "http://localhost:11434"
    assert config.api_key == "test-key"
    assert config.timeout == 30.0
    assert config.max_retries == 3
    assert config.max_concurrent_requests == 10


def test_generation_params_creation():
    """Test GenerationParams model creation."""
    params = GenerationParams(
        temperature=0.7,
        max_tokens=100,
        top_p=0.9,
        frequency_penalty=0.5,
        presence_penalty=0.5,
    )

    assert params.temperature == 0.7
    assert params.max_tokens == 100
    assert params.top_p == 0.9
    assert params.frequency_penalty == 0.5
    assert params.presence_penalty == 0.5


def test_generation_params_validation():
    """Test GenerationParams validation."""
    # Temperature should be between 0 and 2
    with pytest.raises(ValueError):
        GenerationParams(temperature=3.0)

    with pytest.raises(ValueError):
        GenerationParams(temperature=-1.0)

    # Top-p should be between 0 and 1
    with pytest.raises(ValueError):
        GenerationParams(top_p=1.5)

    with pytest.raises(ValueError):
        GenerationParams(top_p=-0.5)


def test_llm_response_creation():
    """Test LLMResponse model creation."""
    token_usage = TokenUsage(
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
    )

    response = LLMResponse(
        content="Test response",
        provider="ollama",
        model="llama3",
        latency_ms=150.5,
        token_usage=token_usage,
        estimated_cost=0.001,
    )

    assert response.content == "Test response"
    assert response.provider == "ollama"
    assert response.model == "llama3"
    assert response.latency_ms == 150.5
    assert response.token_usage.total_tokens == 30
    assert response.estimated_cost == 0.001


def test_token_usage_creation():
    """Test TokenUsage model creation."""
    usage = TokenUsage(
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
    )

    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 20
    assert usage.total_tokens == 30


def test_llm_response_without_optional_fields():
    """Test LLMResponse creation without optional fields."""
    response = LLMResponse(
        content="Test response",
        provider="ollama",
        model="llama3",
        latency_ms=150.5,
    )

    assert response.content == "Test response"
    assert response.token_usage is None
    assert response.estimated_cost is None
