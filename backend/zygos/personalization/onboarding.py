"""Review-before-save personalization onboarding flow (RFC-0010 §2).

Nothing is written until the user confirms at the final prompt. The raw
description lives only in a local variable.

Stability: Experimental.
"""

from __future__ import annotations

from typing import Callable

from pydantic import ValidationError

from zygos.errors import PersonalizationCompileError, ProviderError
from zygos.personalization.compile import compile_personalization
from zygos.personalization.render import render_identity
from zygos.personalization.store import PreferencesStore
from zygos.personalization.types import PERSONALIZATION_FIELDS, Personalization
from zygos.runtime.context import ExecutionContext
from zygos.services.model import ModelService

_INTRO = (
    "Let's personalize Zygos. Describe yourself and the assistant you want in a sentence "
    "or two (your name, how to address you, the assistant's name, its tone). I'll draft "
    "settings from it; you review and edit each field (Enter keeps, - clears) before anything "
    "is saved."
)


def _label(field: str) -> str:
    return field.replace("_", " ").capitalize()


async def run_onboarding(
    ctx: ExecutionContext,
    model: ModelService,
    store: PreferencesStore,
    *,
    ask: Callable[[str], str],
    say: Callable[[str], None],
) -> bool:
    try:
        say(_INTRO)
        if not store.get().is_empty:
            say("This replaces your current settings.")
        description = ask("Describe yourself and the assistant you want (Enter to skip): ").strip()
        if not description:
            say("Skipped. Run `zygos personalize` any time.")
            return False
        try:
            draft = await compile_personalization(ctx, model, description)
        except PersonalizationCompileError as exc:
            say(str(exc))
            return False
        except ProviderError as exc:
            say(
                f"Couldn't reach the model ({exc}). "
                "Try again later, or set fields directly with `zygos personalize set`."
            )
            return False
        del description

        values: dict[str, str | None] = {f: getattr(draft, f) for f in PERSONALIZATION_FIELDS}
        for field in PERSONALIZATION_FIELDS:
            while True:
                answer = ask(f"{_label(field)} [{values[field] or '-'}]: ").strip()
                if answer == "":
                    break
                candidate = {**values, field: None if answer == "-" else answer}
                try:
                    Personalization(**candidate)
                except ValidationError as exc:
                    say(f"Invalid {field}: {exc.errors()[0]['msg']}")
                    continue
                values = candidate
                break

        final = Personalization(**values)
        say("Here is what will be saved:")
        say(render_identity(final) or "(nothing set)")
        if ask("Save? [y/N]: ").strip().lower() not in ("y", "yes"):
            return False
        store.set(final)
        return True
    except EOFError:
        return False
