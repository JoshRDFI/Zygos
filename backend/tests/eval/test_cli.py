import textwrap
import pytest

from zygos.eval.__main__ import run_eval, build_scorers, check_provider_configured
from zygos.reasoning.types import ReasoningResult
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus


class _FakeAssembly:
    def __init__(self):
        self.model_service = _StubModel()
        self.reasoning_service = _FakeReasoning()
        self._bus = InProcessEventBus()

    def new_context(self, *, session_id=None):
        return root_context(self._bus, session_id=session_id)


class _StubModel:
    async def generate(self, ctx, request):
        from zygos.providers.types import GenerationResult
        return GenerationResult(text="1.0", model=request.model, provider="fake")


class _FakeReasoning:
    async def run(self, ctx, input):
        return ReasoningResult(text="4", loops_used=1, final_confidence=0.9,
                               halted_early=True, model="fake")


def _suite(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(textwrap.dedent("""
        suite: demo
        tasks:
          - id: a
            category: simple
            split: val
            input: "2+2?"
            scorer: {kind: exact_match, expected: "4"}
    """))
    return p


@pytest.mark.asyncio
async def test_run_eval_produces_report(tmp_path):
    report = await run_eval(_suite(tmp_path), split="val", category=None,
                            assembly=_FakeAssembly(), judge_model="judge-x")
    assert report.by_split["val"].pass_rate == 1.0


def test_check_provider_configured_flags_missing_key():
    class C:
        class providers:
            class primary:
                provider = "anthropic"
            credentials = {}
    assert check_provider_configured(C) is not None


def test_check_provider_configured_ok_for_local():
    class C:
        class providers:
            class primary:
                provider = "ollama"
            credentials = {}
    assert check_provider_configured(C) is None
