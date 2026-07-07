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


def test_main_runs_eval_and_closes_in_one_event_loop(tmp_path, monkeypatch):
    """Regression: a real run opens an httpx pool bound to the eval's event loop.
    If aclose() runs in a *second* asyncio.run(), closing that pool raises
    'Event loop is closed'. run_eval and aclose must share one loop."""
    import asyncio
    import zygos.runtime.bootstrap as bootstrap
    import zygos.eval.__main__ as cli
    from zygos.eval.report import build_report

    loops = {}

    class _Cfg:
        class reasoning:
            enabled = True
        class providers:
            class primary:
                provider = "ollama"
                model = "qwen3:8b"
            credentials = {}

    class _Assembly:
        config = _Cfg
        async def aclose(self):
            loops["close"] = asyncio.get_running_loop()

    async def _fake_run_eval(*args, **kwargs):
        loops["run"] = asyncio.get_running_loop()
        return build_report("demo", [])

    monkeypatch.setattr(bootstrap, "build_runtime", lambda config_path=None: _Assembly())
    monkeypatch.setattr(cli, "run_eval", _fake_run_eval)

    rc = cli.main([str(tmp_path / "s.yaml")])

    assert rc == 0
    assert loops["run"] is loops["close"], "run_eval and aclose must run in the same event loop"


def test_main_closes_assembly_on_precondition_failure(tmp_path, monkeypatch):
    import zygos.runtime.bootstrap as bootstrap
    from zygos.eval.__main__ import main

    closed = {"aclose": False}

    class _Cfg:
        class reasoning:
            enabled = False
        class providers:
            class primary:
                provider = "ollama"
                model = "m"
            credentials = {}

    class _Assembly:
        config = _Cfg
        async def aclose(self):
            closed["aclose"] = True

    monkeypatch.setattr(bootstrap, "build_runtime", lambda config_path=None: _Assembly())
    rc = main([str(tmp_path / "s.yaml")])
    assert rc == 2
    assert closed["aclose"] is True


def test_build_scorers_includes_code_exec():
    from zygos.eval.__main__ import build_scorers
    from zygos.eval.scorers import CodeExecScorer

    scorers = build_scorers(None, "judge-x")
    assert isinstance(scorers["code_exec"], CodeExecScorer)
