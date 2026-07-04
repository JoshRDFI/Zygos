from zygos.providers.fake import FakeProvider
from zygos.providers.types import GenerationRequest, Message
from zygos.services.model import DefaultModelService, classify_task
from zygos.services.router import ProviderRouter, RouteChoice


def test_classify_task_heuristics():
    assert classify_task("def add(a, b): return a + b") == "code"
    assert classify_task("Why does the circuit breaker design trade off availability?") == "complex_reasoning"
    assert classify_task("hi") == "simple"
    assert classify_task("Summarize the meeting notes from Tuesday about the quarterly report please.") == "standard"


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
    result = await service.generate(request)
    assert result.text == "alpha beta"
    assert result.model == "m1"  # router filled the model
    chunks = [c async for c in service.stream(request)]
    assert chunks[-1].done is True
