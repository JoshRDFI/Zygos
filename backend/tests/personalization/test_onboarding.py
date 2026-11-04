import json

import pytest

from zygos.personalization import Personalization
from zygos.personalization.onboarding import run_onboarding
from zygos.providers.fake import FakeProvider
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.services.model import DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice

DRAFT = {
    "user_name": "Josh", "address": "boss", "pronouns": "he/him",
    "assistant_name": "Rommie", "tone": "dry", "persona": "You are a wry helper.",
}


class _Store:
    def __init__(self):
        self.value = Personalization()
        self.writes = 0

    def get(self):
        return self.value

    def set(self, prefs):
        self.value = prefs
        self.writes += 1


def _model(text):
    router = ProviderRouter([RouteChoice("fake", "m")], {"fake": FakeProvider(text=text)})
    return DefaultModelService(router)


class _Harness:
    def __init__(self, answers):
        self.answers = list(answers)
        self.said = []
        self.prompts = []

    def ask(self, prompt):
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def say(self, text):
        self.said.append(text)


async def _run(answers, draft=DRAFT, text=None):
    h, store = _Harness(answers), _Store()
    ok = await run_onboarding(
        root_context(InProcessEventBus()), _model(text if text is not None else json.dumps(draft)),
        store, ask=h.ask, say=h.say,
    )
    return ok, h, store


@pytest.mark.asyncio
async def test_empty_description_skips_and_store_stays_empty():
    ok, h, store = await _run([""])
    assert ok is False and store.writes == 0
    assert any("Skipped" in s for s in h.said)


@pytest.mark.asyncio
async def test_accept_draft_saves():
    ok, h, store = await _run(["I am Josh"] + [""] * 6 + ["y"])
    assert ok is True and store.value == Personalization(**DRAFT)
    assert any(p.startswith("User name [Josh]") for p in h.prompts)


@pytest.mark.asyncio
async def test_edit_and_clear_fields():
    # order: user_name, address, pronouns, assistant_name, tone, persona
    ok, _, store = await _run(["I am Josh", "", "", "", "Rommie2", "-", "", "YES"])
    assert ok is True
    assert store.value.assistant_name == "Rommie2"
    assert store.value.tone is None
    assert store.value.user_name == "Josh"


@pytest.mark.asyncio
async def test_decline_does_not_save():
    ok, _, store = await _run(["I am Josh"] + [""] * 6 + ["n"])
    assert ok is False and store.writes == 0


@pytest.mark.asyncio
async def test_eof_mid_review_does_not_save():
    ok, _, store = await _run(["I am Josh", "", ""])
    assert ok is False and store.writes == 0


@pytest.mark.asyncio
async def test_compile_error_reports_and_does_not_save():
    ok, h, store = await _run(["I am Josh"], text="no json here")
    assert ok is False and store.writes == 0
    assert any("usable draft" in s for s in h.said)


@pytest.mark.asyncio
async def test_invalid_edit_reasks():
    ok, h, store = await _run(["I am Josh", "x" * 65, "Josh"] + [""] * 5 + ["y"])
    assert ok is True and store.value.user_name == "Josh"
    assert any("user_name" in s for s in h.said)
    assert sum(p.startswith("User name") for p in h.prompts) == 2


@pytest.mark.asyncio
async def test_description_not_persisted():
    ok, _, store = await _run(["PURPLE-ELEPHANT lover"] + [""] * 6 + ["y"])
    assert ok is True
    assert "PURPLE-ELEPHANT" not in store.value.model_dump_json()


@pytest.mark.asyncio
async def test_unreachable_model_reports_and_does_not_save():
    from zygos.errors import ProviderUnavailable

    class _Down(FakeProvider):
        async def generate(self, request):
            raise ProviderUnavailable("connection refused", provider="fake")

    provider = _Down()
    router = ProviderRouter([RouteChoice("fake", "m")], {"fake": provider})
    h, store = _Harness(["I am Josh"]), _Store()
    ok = await run_onboarding(
        root_context(InProcessEventBus()), DefaultModelService(router), store, ask=h.ask, say=h.say,
    )
    assert ok is False and store.writes == 0
    assert any("zygos personalize set" in s for s in h.said)
