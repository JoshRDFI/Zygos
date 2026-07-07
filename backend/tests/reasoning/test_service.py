import asyncio

import pytest

from zygos.config.schema import ReasoningConfig
from zygos.providers.types import GenerationChunk, GenerationResult
from zygos.reasoning.service import DefaultReasoningService
from zygos.reasoning.types import ReasoningInput
from zygos.runtime.context import root_context
from zygos.runtime.events import Event, InProcessEventBus
from zygos.services.model import DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice

PRELUDE = '{"summary": "prelude summary about the topic", "decomposition": ["step a", "step b"]}'


class _StageProvider:
    """Stage-aware fake: replies by inspecting the prompt (which stage built it), so
    the tests are robust to how many recurrent iterations run. Records each request and
    counts judge calls."""

    name = "stage"

    def __init__(self, *, recurrent: str = "refined working summary", judge: float = 0.9) -> None:
        self._recurrent = recurrent
        self._judge = judge
        self.requests: list = []
        self.judge_calls = 0

    async def generate(self, request):
        content = request.messages[0].content
        self.requests.append(request)
        if "Decompose" in content:
            text = PRELUDE
        elif "Synthesize the final answer" in content:
            text = "FINAL ANSWER TEXT"
        elif "Rate how complete" in content:
            self.judge_calls += 1
            text = f'{{"confidence": {self._judge}}}'
        else:  # recurrent "Refine..."
            text = self._recurrent
        return GenerationResult(text=text, model=request.model, provider=self.name)

    async def stream(self, request):
        yield GenerationChunk(text="x", done=True)


def _service(*, recurrent="refined working summary", judge=0.9, profile="balanced", task_routes=None):
    provider = _StageProvider(recurrent=recurrent, judge=judge)
    router = ProviderRouter([RouteChoice("stage", "base")], {"stage": provider})
    model = DefaultModelService(router, task_routes=task_routes or {})
    cfg = ReasoningConfig(enabled=True, profile=profile)
    return DefaultReasoningService(model, cfg), provider


def _recorder():
    events: list[Event] = []

    async def sub(event: Event) -> None:
        events.append(event)

    return events, sub


async def test_runs_prelude_recurrent_coda_and_parses_decomposition():
    svc, provider = _service(profile="shallow")
    result = await svc.run(root_context(InProcessEventBus()), ReasoningInput(prompt="why is it 42"))
    assert result.text == "FINAL ANSWER TEXT"           # coda output, whatever the iteration count
    assert svc.snapshot().stage == "done"
    assert svc.snapshot().decomposition == ("step a", "step b")
    assert len(svc.snapshot().iterations) >= 1
    # a recurrent request actually used a real profile temperature (shallow: base or explore)
    assert any(r.temperature in (0.15, 0.23) for r in provider.requests)


async def test_recurrent_bounded_by_profile_max_iters():
    # a hedged low-signal summary + a judge that never says "exit" -> runs to max_iters
    svc, _ = _service(recurrent="maybe unclear, however that is uncertain", judge=0.0, profile="balanced")
    await svc.run(root_context(InProcessEventBus()), ReasoningInput(prompt="hard one"))
    assert len(svc.snapshot().iterations) == 4          # balanced max_iters
    assert svc.snapshot().halted_early is False


async def test_emits_request_and_model_events_in_order():
    events, sub = _recorder()
    bus = InProcessEventBus()
    bus.subscribe(sub)
    svc, _ = _service(profile="shallow")
    await svc.run(root_context(bus), ReasoningInput(prompt="q"))
    types = [e.type for e in events]
    assert types[0] == "request.started"
    assert "model.selected" in types
    assert types[-1] == "request.finished"


async def test_model_escalation_selects_task_route():
    events, sub = _recorder()
    bus = InProcessEventBus()
    bus.subscribe(sub)
    svc, _ = _service(profile="balanced", task_routes={"complex_reasoning": RouteChoice("stage", "big")})
    await svc.run(root_context(bus), ReasoningInput(prompt="analyze the tradeoff and compare"))
    selected = [e for e in events if e.type == "model.selected"]
    assert selected and selected[0].payload.model == "big"


async def test_shallow_profile_does_not_escalate():
    events, sub = _recorder()
    bus = InProcessEventBus()
    bus.subscribe(sub)
    # shallow.escalate is False -> classification is not used for selection
    svc, _ = _service(profile="shallow", task_routes={"complex_reasoning": RouteChoice("stage", "big")})
    await svc.run(root_context(bus), ReasoningInput(prompt="analyze the tradeoff and compare"))
    selected = [e for e in events if e.type == "model.selected"]
    assert selected and selected[0].payload.model == "base"


async def test_cancellation_skips_coda_and_returns_best_so_far():
    svc, provider = _service(profile="deep")
    ctx = root_context(InProcessEventBus())
    ctx._cancel.trip()  # cancelled before the loop's first check
    result = await svc.run(ctx, ReasoningInput(prompt="q"))
    snap = svc.snapshot()
    assert snap.cancelled is True
    assert snap.stage == "cancelled"
    assert result.text  # best-so-far (prelude summary); never raised
    # coda was skipped on cancellation
    assert not any("Synthesize the final answer" in r.messages[0].content for r in provider.requests)


async def test_run_rejects_concurrent_run():
    import asyncio

    from zygos.config.schema import ReasoningConfig
    from zygos.reasoning.service import DefaultReasoningService
    from zygos.services.model import DefaultModelService
    from zygos.services.router import ProviderRouter, RouteChoice

    class _BlockingProvider:
        name = "block"

        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def generate(self, request):
            self.entered.set()
            await self.release.wait()
            return GenerationResult(
                text='{"summary": "s", "decomposition": []}', model=request.model, provider=self.name
            )

        async def stream(self, request):
            yield GenerationChunk(text="x", done=True)

    provider = _BlockingProvider()
    router = ProviderRouter([RouteChoice("block", "m")], {"block": provider})
    svc = DefaultReasoningService(DefaultModelService(router), ReasoningConfig(enabled=True, profile="shallow"))
    run1 = asyncio.create_task(svc.run(root_context(InProcessEventBus()), ReasoningInput(prompt="a")))
    await provider.entered.wait()  # run1 is in-flight, blocked in the prelude call
    with pytest.raises(RuntimeError):
        await svc.run(root_context(InProcessEventBus()), ReasoningInput(prompt="b"))
    provider.release.set()
    await run1  # run1 finishes cleanly; the guard is cleared


async def test_judge_request_is_not_token_starved():
    # The fence-judge sub-call must not be starved: a thinking judge model spends
    # a tiny budget inside its reasoning and returns empty content. Judge requests
    # carry a generous (adaptive) budget like the other stages.
    # This recurrent summary scores just inside the fence band on iteration 1,
    # so the judge is consulted (and a judge request is recorded).
    svc, provider = _service(
        recurrent="prelude summary about the topic step a step b therefore the result",
        judge=0.9, profile="balanced",
    )
    await svc.run(root_context(InProcessEventBus()), ReasoningInput(prompt="hard one"))
    judge_reqs = [r for r in provider.requests if "Rate how complete" in r.messages[0].content]
    assert judge_reqs, "judge stage should have fired in this scenario"
    assert all(r.max_tokens >= 256 for r in judge_reqs)


async def test_recurrent_request_carries_adaptive_token_budget():
    from zygos.reasoning import adaptive
    from zygos.reasoning.profiles import resolve_profile

    svc, provider = _service(profile="shallow")
    await svc.run(root_context(InProcessEventBus()), ReasoningInput(prompt="why is it 42"))
    profile = resolve_profile("shallow")
    complexity = adaptive.task_complexity("why is it 42", ("step a", "step b"))
    expected = adaptive.token_budget(profile, complexity)
    recurrent = [r for r in provider.requests if "Refine" in r.messages[0].content]
    assert recurrent and all(r.max_tokens == expected for r in recurrent)
