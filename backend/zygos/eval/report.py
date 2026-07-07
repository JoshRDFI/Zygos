"""Report aggregation — pure. Stability: Experimental."""

from collections.abc import Sequence

from zygos.eval.types import EvalReport, RunRecord, SplitSummary


def _summarize(records: Sequence[RunRecord]) -> SplitSummary:
    scored = [r for r in records if r.score is not None]
    errors = sum(1 for r in records if r.score is None)
    n = len(scored)
    mean = sum(r.score for r in scored) / n if n else 0.0
    passed = sum(1 for r in scored if r.passed) / n if n else 0.0
    return SplitSummary(n=n, errors=errors, mean_score=mean, pass_rate=passed)


def _group(records: Sequence[RunRecord], key) -> dict[str, SplitSummary]:
    buckets: dict[str, list[RunRecord]] = {}
    for r in records:
        buckets.setdefault(key(r), []).append(r)
    return {k: _summarize(v) for k, v in buckets.items()}


def build_report(suite: str, records: Sequence[RunRecord]) -> EvalReport:
    return EvalReport(
        suite=suite,
        records=tuple(records),
        by_split=_group(records, lambda r: r.split),
        by_category=_group(records, lambda r: r.category),
        by_scorer=_group(records, lambda r: r.scorer_kind),
        errors=sum(1 for r in records if r.score is None),
    )


def render_table(report: EvalReport) -> str:
    lines = [f"suite: {report.suite}  (errors: {report.errors})", ""]
    for title, group in (("by split", report.by_split), ("by category", report.by_category),
                         ("by scorer", report.by_scorer)):
        lines.append(title)
        for name, s in sorted(group.items()):
            lines.append(
                f"  {name:<18} n={s.n:<3} errors={s.errors:<3} "
                f"mean={s.mean_score:.3f} pass={s.pass_rate:.1%}"
            )
        lines.append("")
    return "\n".join(lines)
