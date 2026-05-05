"""
Tests for config-driven LLM provider chain (Step 2 — chain flip).

Coverage
────────
1. Default config wires OpenAI as primary and Groq as fallback; backwards-compat
   aliases (_groq, _openai, _groq_cb) point to the right objects.
2. Reversed config (LLM_PRIMARY_PROVIDER=groq) wires Groq as primary.
3. Startup validation rejects same-provider for primary and fallback.
4. Startup validation rejects missing primary API key.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test 1 — default order: OpenAI primary, Groq fallback
# ---------------------------------------------------------------------------

def test_provider_order_config_driven():
    """
    With LLM_PRIMARY_PROVIDER=openai (default after chain flip):
    - _primary_name must be "openai", _fallback_name must be "groq"
    - Backwards-compat aliases must point to the correct objects
    - _build_client must be called with "openai" first, then "groq"
    """
    from llm.llm_client import LLMClient

    fake_settings = SimpleNamespace(
        llm_primary_provider="openai",
        llm_fallback_provider="groq",
        llm_primary_model="gpt-4o-mini",
        llm_fallback_model="llama-3.3-70b-versatile",
        llm_primary_timeout_s=8.0,
        llm_fallback_timeout_s=4.0,
        llm_circuit_fail_threshold=2,
        llm_circuit_cooldown_s=120.0,
        openai_api_key="sk-test-openai",
        groq_api_key="gsk-test-groq",
    )

    with patch("llm.llm_client.settings", fake_settings), \
         patch("llm.llm_client._build_client", return_value=MagicMock()) as mock_build:
        llm = LLMClient()

    assert llm._primary_name  == "openai"
    assert llm._fallback_name == "groq"

    # Backwards-compat aliases must reference the same objects
    assert llm._groq    is llm._primary
    assert llm._openai  is llm._fallback
    assert llm._groq_cb is llm._primary_cb

    # _build_client called twice: first for primary, then fallback
    assert mock_build.call_count == 2
    assert mock_build.call_args_list[0][0][0] == "openai"
    assert mock_build.call_args_list[1][0][0] == "groq"


# ---------------------------------------------------------------------------
# Test 2 — reversed order: Groq primary, OpenAI fallback
# ---------------------------------------------------------------------------

def test_provider_order_reversed():
    """
    With LLM_PRIMARY_PROVIDER=groq (the original pre-flip config):
    - _primary_name must be "groq", _fallback_name must be "openai"
    - _build_client must be called with "groq" first, then "openai"
    """
    from llm.llm_client import LLMClient

    fake_settings = SimpleNamespace(
        llm_primary_provider="groq",
        llm_fallback_provider="openai",
        llm_primary_model="llama-3.3-70b-versatile",
        llm_fallback_model="gpt-4o-mini",
        llm_primary_timeout_s=4.0,
        llm_fallback_timeout_s=8.0,
        llm_circuit_fail_threshold=2,
        llm_circuit_cooldown_s=120.0,
        openai_api_key="sk-test-openai",
        groq_api_key="gsk-test-groq",
    )

    with patch("llm.llm_client.settings", fake_settings), \
         patch("llm.llm_client._build_client", return_value=MagicMock()) as mock_build:
        llm = LLMClient()

    assert llm._primary_name  == "groq"
    assert llm._fallback_name == "openai"
    assert mock_build.call_args_list[0][0][0] == "groq"
    assert mock_build.call_args_list[1][0][0] == "openai"


# ---------------------------------------------------------------------------
# Test 3 — startup rejects same provider for both roles
# ---------------------------------------------------------------------------

def test_startup_fails_if_same_provider_for_primary_and_fallback():
    """
    _validate_llm_config must raise RuntimeError when primary == fallback.
    """
    from main import _validate_llm_config
    from llm.llm_client import PROVIDER_CONFIG

    fake_settings = SimpleNamespace(
        llm_primary_provider="openai",
        llm_fallback_provider="openai",   # same as primary
        openai_api_key="sk-test",
        groq_api_key="gsk-test",
    )

    with pytest.raises(RuntimeError, match="both"):
        _validate_llm_config(fake_settings, PROVIDER_CONFIG)


# ---------------------------------------------------------------------------
# Test 4 — startup rejects missing primary API key
# ---------------------------------------------------------------------------

def test_startup_fails_if_primary_api_key_missing():
    """
    _validate_llm_config must raise RuntimeError when the primary provider's
    API key is absent (None or empty string).
    """
    from main import _validate_llm_config
    from llm.llm_client import PROVIDER_CONFIG

    fake_settings = SimpleNamespace(
        llm_primary_provider="openai",
        llm_fallback_provider="groq",
        openai_api_key=None,   # missing primary key
        groq_api_key="gsk-test",
    )

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        _validate_llm_config(fake_settings, PROVIDER_CONFIG)
