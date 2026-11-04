"""Compile a free-text description into a Personalization draft (RFC-0010 §2).

The description is passed to the model and never logged or stored.

Stability: Experimental.
"""

from __future__ import annotations

from zygos.errors import PersonalizationCompileError
from zygos.personalization.types import FIELD_MAX_LENGTHS, PERSONALIZATION_FIELDS, Personalization
from zygos.providers.types import GenerationRequest, Message
from zygos.reasoning.prompts import _extract_json
from zygos.runtime.context import ExecutionContext
from zygos.services.model import ModelService

_INSTRUCTIONS = (
    "Read the description below, written by a user about themselves and the AI assistant "
    "they want. Reply with exactly one JSON object with these six keys, each a string or "
    "null: " + ", ".join(PERSONALIZATION_FIELDS) + ". "
    '"persona" must be 1-3 sentences in the second person ("You are...") capturing '
    "tone and personality only. Never invent names the description does not give; use "
    "null for anything not stated. Output only the JSON object.\n\nDescription:\n"
)


async def compile_personalization(ctx: ExecutionContext, model: ModelService, description: str) -> Personalization:
    request = GenerationRequest(
        messages=(Message(role="user", content=_INSTRUCTIONS + description),),
        temperature=0.2,
    )
    result = await model.generate(ctx, request)
    obj = _extract_json(result.text)
    if obj is None:
        raise PersonalizationCompileError("The model did not return a usable draft; try again or set fields directly.")
    kept = {
        f: obj[f].strip()[: FIELD_MAX_LENGTHS[f]]
        for f in PERSONALIZATION_FIELDS
        if isinstance(obj.get(f), str)
    }
    return Personalization(**kept)
