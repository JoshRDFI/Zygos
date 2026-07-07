"""vLLM provider — OpenAI-compatible protocol against a local server.

Keyless by default; base_url points at the local vLLM instance
(default http://localhost:8000/v1) and model names pass through verbatim,
so any locally served model works unmodified.

Stability: Experimental. See RFC-0001 section on provider stability.
"""

from zygos.providers.openai import OpenAIProvider


class VllmProvider(OpenAIProvider):
    name = "vllm"
    # ADR-0006: local backend -> uncapped by default (omit max_tokens when the caller
    # gives none), unlike the cloud OpenAI default.
    default_max_tokens = None
