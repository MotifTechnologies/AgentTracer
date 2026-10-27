from unittest.mock import Mock

import pytest

from agent_tracer.config.schema import ModelConfig
from agent_tracer.models import client as client_module


@pytest.mark.parametrize("use_env", [False, True])
def test_build_client_forwards_every_model_setting(monkeypatch, use_env):
    monkeypatch.setenv("CLIENT_MAPPING_TEST_KEY", "test-only-key")
    settings = {
        "model_name": "test/model",
        "base_url": "https://example.invalid/v1",
        "api_key": "env:CLIENT_MAPPING_TEST_KEY" if use_env else "test-only-key",
        "reasoning_key": "thinking",
        "max_tokens": 777,
        "send_max_tokens": False,
        "context_window_tokens": 64000,
        "reasoning_effort": "low",
        "timeout": 42.5,
        "max_retries": 0,
        "extra_kwargs": {"temperature": 0.2, "extra_body": {"top_k": 7}},
    }
    # Adding a config field requires an explicit forwarding/omission decision.
    assert set(settings) == set(ModelConfig.model_fields)
    constructor = Mock()
    monkeypatch.setattr(client_module, "ReasoningKeyChatClient", constructor)

    result = client_module.build_client(ModelConfig(**settings))

    assert result is constructor.return_value
    constructor.assert_called_once_with(
        "test/model",
        777,
        context_window_tokens=64000,
        base_url="https://example.invalid/v1",
        api_key="test-only-key",
        reasoning_key="thinking",
        send_max_tokens=False,
        reasoning_effort="low",
        timeout=42.5,
        max_retries=0,
        kwargs={"temperature": 0.2, "extra_body": {"top_k": 7}},
    )
