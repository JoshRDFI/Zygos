import json

import pytest

from zygos.errors import PersonalizationCompileError
from zygos.personalization.compile import compile_personalization
from zygos.providers.fake import FakeProvider
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.services.model import DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice


class _Rec(FakeProvider):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return await super().generate(request)


def _model(text):
    provider = _Rec(text=text)
    router = ProviderRouter([RouteChoice("fake", "m")], {"fake": provider})
    return DefaultModelService(router), provider


def _ctx():
    return root_context(InProcessEventBus())


@pytest.mark.asyncio
async def test_one_call_extracts_fields_and_persona():
    model, provider = _model(json.dumps({
        "user_name": "Josh", "address": "boss", "pronouns": "he/him",
        "assistant_name": "Rommie", "tone": "dry", "persona": "You are a wry helper.",
    }))
    prefs = await compile_personalization(_ctx(), model, "I'm Josh, call me boss. PURPLE-ELEPHANT")
    assert prefs.user_name == "Josh" and prefs.assistant_name == "Rommie"
    assert prefs.persona == "You are a wry helper."
    assert len(provider.requests) == 1
    req = provider.requests[0]
    assert len(req.messages) == 1 and req.messages[0].role == "user"
    assert "PURPLE-ELEPHANT" in req.messages[0].content
    assert req.temperature == 0.2


@pytest.mark.asyncio
async def test_fenced_json_with_prose_accepted():
    model, _ = _model('Sure!\n```json\n{"user_name": "Josh"}\n```\nDone.')
    prefs = await compile_personalization(_ctx(), model, "x")
    assert prefs.user_name == "Josh"


@pytest.mark.asyncio
async def test_unknown_keys_and_non_strings_dropped():
    model, _ = _model('{"user_name": "Josh", "age": 40, "tone": null, "x": "y"}')
    prefs = await compile_personalization(_ctx(), model, "x")
    assert prefs.user_name == "Josh"
    assert prefs.tone is None and prefs.address is None
    assert not hasattr(prefs, "age")


@pytest.mark.asyncio
async def test_overlong_persona_clipped_to_600():
    model, _ = _model(json.dumps({"persona": "a" * 900}))
    prefs = await compile_personalization(_ctx(), model, "x")
    assert prefs.persona is not None and len(prefs.persona) == 600


@pytest.mark.asyncio
async def test_no_json_raises_compile_error():
    model, _ = _model("I cannot do that.")
    with pytest.raises(PersonalizationCompileError, match="did not return a usable draft"):
        await compile_personalization(_ctx(), model, "x")
