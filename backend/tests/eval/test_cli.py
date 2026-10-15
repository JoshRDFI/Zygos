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
        model_service = None
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


def _fake_runtime(tmp_path):
    from zygos.runtime.bootstrap import build_runtime
    cfg = tmp_path / "c.yaml"
    cfg.write_text("providers:\n  primary:\n    provider: fake\n    model: contestant\n"
                   "reasoning:\n  enabled: true\n")
    return build_runtime(cfg)


@pytest.mark.asyncio
async def test_judge_service_routes_to_the_judge_model(tmp_path):
    """Regression (2026-10-15): --judge-model was ignored because the router fills
    request.model from its route, so the model under test graded itself."""
    from zygos.eval.__main__ import judge_model_service
    from zygos.providers.types import GenerationRequest, Message
    assembly = _fake_runtime(tmp_path)
    try:
        judge = judge_model_service(assembly, "judge-x")
        result = await judge.generate(
            assembly.new_context(), GenerationRequest(messages=(Message(role="user", content="score"),)))
        assert result.model == "judge-x"
    finally:
        await assembly.aclose()


@pytest.mark.asyncio
async def test_judge_service_is_the_runtime_service_when_judge_is_the_contestant(tmp_path):
    from zygos.eval.__main__ import judge_model_service
    assembly = _fake_runtime(tmp_path)
    try:
        assert judge_model_service(assembly, "contestant") is assembly.model_service
    finally:
        await assembly.aclose()


@pytest.mark.asyncio
async def test_run_eval_scores_with_the_given_judge_service(tmp_path):
    seen = []

    class _Judge:
        async def generate(self, ctx, request):
            from zygos.providers.types import GenerationResult
            seen.append(request)
            return GenerationResult(text="1.0", model="judge-x", provider="fake")

    p = tmp_path / "j.yaml"
    p.write_text(textwrap.dedent("""
        suite: demo
        tasks:
          - id: a
            category: simple
            split: val
            input: "Why is the sky blue?"
            scorer: {kind: llm_judge, rubric: "Rayleigh"}
    """))
    report = await run_eval(p, split=None, category=None, assembly=_FakeAssembly(),
                            judge_model="judge-x", judge_service=_Judge())
    assert len(seen) == 1
    assert report.by_split["val"].pass_rate == 1.0


def test_main_warns_when_the_model_grades_itself(tmp_path, monkeypatch, capsys):
    import zygos.runtime.bootstrap as bootstrap
    import zygos.eval.__main__ as cli
    from zygos.eval.report import build_report

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
        model_service = object()
        async def aclose(self):
            pass

    async def _fake_run_eval(*args, **kwargs):
        return build_report("demo", [])

    monkeypatch.setattr(bootstrap, "build_runtime", lambda config_path=None: _Assembly())
    monkeypatch.setattr(cli, "run_eval", _fake_run_eval)

    assert cli.main([str(tmp_path / "s.yaml")]) == 0
    assert "grades its own" in capsys.readouterr().err
