# RDT Reasoning Guide (Phase 5)

This guide describes how Zygos executes Recurrent-Depth Transformer (RDT) reasoning as a **runtime orchestration pattern** over standard provider APIs (Ollama/vLLM/OpenAI-compatible/Anthropic-compatible).

## What RDT adds

When enabled, a turn can run through:
1. **Prelude**: problem decomposition + latent state initialization
2. **Recurrent**: iterative refinement loop with confidence gating
3. **Coda**: final answer synthesis from best iteration

RDT is optional and controlled by config/CLI.

## Enabling RDT

### Config
Set in `config/default.yaml` (or custom config):

```yaml
rdt:
  enabled: true
  profile: balanced
```

### CLI

```bash
npm run dev -- "Explain the tradeoffs" --rdt true --rdt-profile deep
```

Supported profiles:
- `shallow`: faster, fewer loops
- `balanced`: default quality/speed balance
- `deep`: more iterations + revision budget

## RDT events

During execution, the engine emits:
- `rdt_progress` for detailed stage/iteration events
- `rdt_observability` for summarized metrics

Notable progress event types:
- `rdt_stage_started` / `rdt_stage_completed`
- `rdt_iteration_completed`
- `rdt_backtrack`
- `rdt_parallel_path`
- `rdt_early_exit`
- `rdt_quality`
- `rdt_trace`

## Confidence model

`src/reasoning/confidence.ts` computes iteration confidence from:
- **Coherence**: overlap and stability with prior state
- **Completeness**: decomposition coverage + answer adequacy
- **Consistency**: contradiction/uncertainty penalty heuristics

The evaluator supports:
- adaptive threshold updates
- smoothing across iterations
- early-exit and revision decisions

## Attention and MoE routing

`src/reasoning/attention.ts` simulates:
- **MLA/GQA mode selection** based on complexity and confidence
- **Sparse MoE routing** (`routedExperts`, `sharedExperts`, `topK`)
- expert load balancing and compute-adaptive allocation

## QueryEngine integration

`src/core/engine.ts` runs RDT in `RDT_OPTIONAL` state when enabled.
Final turn payload may include:

```ts
result.rdt = {
  enabled: true,
  loopsUsed,
  haltedEarly,
  finalConfidence,
  quality: {
    avgCoherence,
    avgCompleteness,
    avgConsistency,
    avgAggregate
  }
}
```

## Test coverage

RDT tests are under:
- `test/reasoning/confidence.test.ts`
- `test/reasoning/attention.test.ts`
- `test/reasoning/rdt-runtime.test.ts`
- `test/core/engine-rdt.test.ts`

Run with:

```bash
npm run test
```
