"""Capability model, contract map, registry (RFC-0003 §1, §3-4).

The registry holds no event bus and no subscription (RFC-0002 invariant):
resolution reads health synchronously via an injected health source.

Stability: Experimental.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from zygos.providers.base import Provider


class Capability(StrEnum):
    LOCAL_INFERENCE = "local_inference"
    VISION = "vision"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    WEB_SEARCH = "web_search"
    IMAGE_GENERATION = "image_generation"
    SCHEDULING = "scheduling"
    FILESYSTEM_ACCESS = "filesystem_access"


# Each capability binds to the contract a satisfier must implement. Only
# capabilities whose contract type exists today appear here; the rest are
# named-but-uncontracted until their RFCs land (RFC-0003 §1). register()
# rejects any capability with no entry here.
CAPABILITY_CONTRACTS: Mapping[Capability, type] = {
    Capability.LOCAL_INFERENCE: Provider,
}
