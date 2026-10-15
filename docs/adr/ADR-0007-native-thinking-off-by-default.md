# ADR-0007: Native Model Thinking Off by Default

**Status:** Accepted
**Date:** 2026-10-15

## Context

Thinking-capable local models (qwen3, gemma4, qwen3.5) reason in a hidden block before they answer. Zygos never sent Ollama's `think` field, so these models used their own default, which is to think on every request. [ADR-0006](ADR-0006-provider-class-token-limits.md) records the July 2026 eval-pilot decision to orchestrate the RDT engine *over* a thinking model, and that held as the default for every turn, including chat and voice.

Voice changed the trade-off. Time to first audio is the main voice-latency metric, and thinking adds seconds before the first answer token. A latency probe on 2026-10-15 (RTX 5080, Ollama 0.34, 10 short conversational prompts plus 4 tool-call prompts, Zygos tool schemas attached) measured the median time to the first answer token:

| Model | Thinking off | Thinking on |
|---|---|---|
| qwen3:8b | 0.03 s | 1.60 s |
| qwen3.5 | 0.22 s | 1.40 s |
| gemma4 (E4B) | 0.16 s | 2.19 s |

Tool-call correctness was 4/4 in every configuration. Thinking does buy accuracy on hard tasks. On the `reasoning-seed-v1` suite, run through the RDT engine, qwen3:8b passed 23/32 with thinking off and 31/32 with it on, and gemma4 passed 29/32 off and 31/32 on. The cost is roughly 10× per task: 3.9 s against 39 s median for qwen3:8b.

## Decision

Native model thinking is **off by default** and is set through config. `providers.think` (default `false`) flows into `ProviderSettings.think`, and a request may override it with `GenerationRequest.think`. `None` at both levels leaves the model's own default. Today only the Ollama provider reads the setting; it sends `think` when the resolved value is not `None`. Thinking stays available as an explicit opt-in: `providers.think: true` now, and later a per-turn UI toggle or voice command through `GenerationRequest.think`. This refines ADR-0006's "orchestrate over a thinking model" from the default for every turn into a mode the user turns on.

## Consequences

- Chat and voice turns start answering in well under a second on local models, which removes the largest single LLM-side delay from time to first audio.
- RDT reasoning turns and the eval harness also run without native thinking unless the config enables it. Expect lower scores on hard multi-step problems in the default configuration. Eval runs that study the reasoning stack should state their `think` setting.
- The per-turn toggle (UI and voice command) is not built. Until it exists, enabling thinking is a config change that applies to every request.
- Providers other than Ollama ignore the setting. Mapping it to vLLM chat-template flags or cloud "extended thinking" parameters is future work, to be added per provider and in the same shape.
