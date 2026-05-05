# Compatibility shim — all implementation moved to llm/llm_client.py
from llm.llm_client import (  # noqa: F401
    LLMClient,
    _CircuitBreaker,
    _CBState,
    _split_sentence,
    _is_auth_error,
    PROVIDER_CONFIG,
)
