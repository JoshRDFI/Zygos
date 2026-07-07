# ADR-0006: Provider-Class-Aware Token Limits

**Status:** Accepted
**Date:** 2026-07-07

## Context

The Cycle-2 reasoning engine ([RFC-0002](../rfcs/RFC-0002-Runtime-Event-Bus-and-ExecutionContext.md) milestone) made per-task token budgeting one of four honest adaptive knobs (iteration count, temperature, **token budget**, model escalation): `adaptive.token_budget` scales a base budget by task complexity and passes it as `GenerationRequest.max_tokens`, which providers map to their generation cap (ollama `num_predict`).

The first live exercise of the eval harness (qwen3:8b, a thinking model, via local ollama) showed this is actively harmful on a thinking model: the cap is consumed *inside* the model's `<think>` block, so the visible answer truncates to empty. The same defect appeared wherever a small fixed cap met a thinking model — the eval judge scorer (`max_tokens=16`) and the reasoning fence-judge stage (`max_tokens=64`) both returned empty content and silently failed. The failure is model-dependent by nature: token appetite varies and rises across models (e.g. Fable spends more than Opus, sometimes for better output outside coding), so any hardcoded ceiling silently starves a hungrier model.

Two provider classes differ fundamentally. **Local** inference (ollama/vllm) has no per-token cost — it is bounded by hardware time and the context window, so a token cap buys nothing and only risks truncation. **Cloud** inference (anthropic/openai) bills per token and needs a real cap for cost and safety.

## Decision

Token limiting becomes provider-class-aware. `GenerationRequest.max_tokens` becomes optional (`int | None`); `None` means "no caller-specified cap — apply the provider's default policy." Local providers treat `None` as uncapped (generate until natural stop or the context window), bounded operationally by the request timeout. Cloud providers treat `None` as a generous, **configurable, model-aware** default — never a hardcoded small constant — revisited as models change. The RDT reasoning stages stop computing a per-task budget and pass `None`, delegating compute allocation to the model's own self-paced reasoning; the harness's remaining adaptive knobs are temperature, iteration count, and model escalation. An explicit integer `max_tokens` is still honored everywhere a caller genuinely wants a cap.

## Consequences

This retires the token-budget knob from the Cycle-2 adaptive set for local inference, and is recorded here per the arch-debt rule so it is not a silent walk-back. "More compute for harder tasks" is preserved but **moves from the harness to the model** — a thinking model thinks longer on harder problems — consistent with the decision to orchestrate *over* a thinking model rather than replace its reasoning. The operational backstop shifts from token count to the request **timeout** (generous enough for long thinking, finite enough to kill a wedged or looping call) and the context window (`num_ctx`), which may need raising for long reasoning. Cloud token caps are now explicitly model-dependent and config-driven; a hardcoded small cap is henceforth treated as the bug class this ADR resolves. The change refines the typed provider contract of [RFC-0001](../rfcs/RFC-0001-Service-Architecture.md) §7 additively — existing integer caps are unchanged — and adds a config surface for the cloud default (a generous constant now, a config hook deferred). Local runs may occasionally run long; on hardware with no per-token cost this is an accepted trade-off.
