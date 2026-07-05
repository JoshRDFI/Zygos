from zygos.providers.fake import FakeProvider
from zygos.providers.types import GenerationRequest, Message
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.services.model import DefaultModelService, classify_task
from zygos.services.router import ProviderRouter, RouteChoice


def _ctx():
    return root_context(InProcessEventBus())


def test_classify_task_heuristics():
    assert classify_task("def add(a, b): return a + b") == "code"
    assert classify_task("Why does the circuit breaker design trade off availability?") == "complex_reasoning"
    assert classify_task("hi") == "simple"
    assert classify_task("Summarize the meeting notes from Tuesday about the quarterly report for the team please.") == "standard"
    # Boundary tests: threshold is exactly 80 characters
    assert classify_task("a" * 79) == "simple"
    assert classify_task("a" * 80) == "standard"
    # Precedence: code markers win over reasoning keywords
    assert classify_task("Why does def foo(x): work?") == "code"
    assert classify_task("analyze this: import os; os.listdir()") == "code"
    # Trade-off keyword branch: must contain only trade-?off, no other reasoning keywords or code markers
    assert classify_task("List every tradeoff in the caching strategy") == "complex_reasoning"


def _service(text: str = "ok") -> DefaultModelService:
    router = ProviderRouter([RouteChoice("fake", "m1")], {"fake": FakeProvider(text=text)})
    return DefaultModelService(router)


def test_select_model_returns_first_eligible_route():
    choice = _service().select_model()
    assert (choice.provider, choice.model) == ("fake", "m1")
    assert _service().select_model(classification="code").model == "m1"  # accepted, unused in M2


async def test_generate_and_stream_delegate_to_router():
    service = _service(text="alpha beta")
    request = GenerationRequest(messages=(Message(role="user", content="hi"),))
    result = await service.generate(_ctx(), request)
    assert result.text == "alpha beta"
    assert result.model == "m1"  # router filled the model
    chunks = [c async for c in service.stream(_ctx(), request)]
    assert chunks[-1].done is True
