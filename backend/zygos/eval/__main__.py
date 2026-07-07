"""Opt-in eval CLI: python -m zygos.eval <suite> [...]. Stability: Experimental."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from zygos.config.schema import ZygosConfig
from zygos.eval.report import EvalReport, build_report, render_table
from zygos.eval.runner import EvalRunner
from zygos.eval.scorers import CodeExecScorer, LlmJudgeScorer, Scorer, match_scorers
from zygos.eval.suite import load_suite
from zygos.services.model import ModelService

_LOCAL_PROVIDERS = {"ollama", "vllm", "fake"}


def build_scorers(model: ModelService, judge_model: str) -> dict[str, Scorer]:
    scorers = match_scorers()
    scorers["llm_judge"] = LlmJudgeScorer(model, judge_model=judge_model)
    scorers["code_exec"] = CodeExecScorer()
    return scorers


def check_provider_configured(config: ZygosConfig) -> str | None:
    provider = config.providers.primary.provider
    if provider in _LOCAL_PROVIDERS:
        return None
    cred = config.providers.credentials.get(provider)
    if cred is None or getattr(cred, "api_key", None) in (None, ""):
        return f"primary provider {provider!r} has no api_key configured"
    return None


async def run_eval(suite_path, *, split, category, assembly, judge_model) -> EvalReport:
    suite = load_suite(suite_path)
    tasks = suite.filter(split=split, category=category)
    scorers = build_scorers(assembly.model_service, judge_model)
    runner = EvalRunner(assembly.reasoning_service, scorers, assembly.new_context)
    records = await runner.run(tasks)
    return build_report(suite.name, records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m zygos.eval")
    parser.add_argument("suite", type=Path)
    parser.add_argument("--split", choices=["train", "val"], default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    from zygos.runtime.bootstrap import build_runtime  # local import: only real runs pay for it

    assembly = build_runtime(args.config)
    config: ZygosConfig = assembly.config

    # Precondition failures: nothing has touched the event loop / http pool yet,
    # so a standalone aclose() is safe.
    if not config.reasoning.enabled:
        print("error: reasoning is disabled; set reasoning.enabled=true in config", file=sys.stderr)
        asyncio.run(assembly.aclose())
        return 2
    err = check_provider_configured(config)
    if err is not None:
        print(f"error: {err}", file=sys.stderr)
        asyncio.run(assembly.aclose())
        return 2

    judge_model = args.judge_model or config.providers.primary.model

    async def _run_and_close() -> EvalReport:
        # run_eval and aclose MUST share one event loop: the run opens an httpx
        # connection pool bound to this loop; closing it in a second asyncio.run()
        # raises 'Event loop is closed'.
        try:
            return await run_eval(
                args.suite, split=args.split, category=args.category,
                assembly=assembly, judge_model=judge_model,
            )
        finally:
            await assembly.aclose()

    report = asyncio.run(_run_and_close())

    print(render_table(report))
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps([r.model_dump() for r in report.records], indent=2))
        print(f"\nwrote {len(report.records)} records to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
