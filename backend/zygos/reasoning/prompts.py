"""Prompt builders + tolerant response parsing for the reasoning stages.

Stability: Experimental.
"""

import json
import re

_NUMBER = re.compile(r"[-+]?\d*\.?\d+")


def build_prelude(prompt: str, context: tuple[str, ...]) -> str:
    ctx = ("\n\nRecent context:\n" + "\n".join(context)) if context else ""
    return (
        "Decompose the user problem into explicit steps and produce a short working "
        "summary. Return strict JSON: "
        '{"summary": string, "decomposition": string[]}.\n\n'
        f"Problem:\n{prompt}{ctx}"
    )


def build_recurrent(prompt: str, decomposition: tuple[str, ...], prior_summary: str, iteration: int) -> str:
    steps = "\n".join(f"- {step}" for step in decomposition) or "- (none)"
    return (
        f"Refine the working summary for iteration {iteration}. Improve coverage and "
        "resolve gaps. Return strict JSON: {\"summary\": string}.\n\n"
        f"Problem:\n{prompt}\n\nDecomposition:\n{steps}\n\nPrevious summary:\n{prior_summary}"
    )


def build_coda(prompt: str, best_summary: str) -> str:
    return (
        "Synthesize the final answer from the best working summary. Return plain text "
        "only (no JSON).\n\n"
        f"Problem:\n{prompt}\n\nBest summary:\n{best_summary}"
    )


def build_judge(prompt: str, summary: str) -> str:
    return (
        "Rate how complete and correct this answer is for the problem, from 0.0 to 1.0. "
        'Return strict JSON: {"confidence": number}.\n\n'
        f"Problem:\n{prompt}\n\nAnswer:\n{summary}"
    )


def _extract_json(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def parse_prelude(text: str) -> tuple[str, tuple[str, ...]]:
    obj = _extract_json(text)
    if obj is None:
        return text.strip(), ()
    summary = str(obj.get("summary", "")).strip() or text.strip()
    decomposition = tuple(str(s) for s in obj.get("decomposition", []) if str(s).strip())
    return summary, decomposition


def parse_summary(text: str) -> str:
    obj = _extract_json(text)
    if obj is not None and "summary" in obj:
        return str(obj["summary"]).strip()
    return text.strip()


def parse_judge(text: str) -> float:
    obj = _extract_json(text)
    if obj is not None and "confidence" in obj:
        try:
            return max(0.0, min(1.0, float(obj["confidence"])))
        except (TypeError, ValueError):
            pass
    match = _NUMBER.search(text)
    if match:
        try:
            return max(0.0, min(1.0, float(match.group())))
        except ValueError:
            return 0.0
    return 0.0
