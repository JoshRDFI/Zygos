# ADR-0008: Client-Side Rate Limiting Is Opt-In

**Status:** Accepted
**Date:** 2026-10-15

## Context

`ProviderRouter` keeps a sliding 60-second request window for each provider and skips a route whose window is full. The default cap was 60 requests per minute, applied to every provider, including local Ollama, which has no quota.

One RDT reasoning turn makes many model calls (the prelude, recurrent loops, confidence and fence judging, and the coda). During a 2026-10-15 eval run against local Ollama, the window filled within the first few tasks. The router then reported `No eligible provider routes` for 23 of 32 tasks, which the harness recorded as task errors, although the model and server were healthy. The same can happen in the live app on any burst of reasoning or tool-loop turns.

Checking for "local" doesn't fix this cleanly. The `LOCAL_INFERENCE` capability is declared by cloud providers too (`openai`, `anthropic`), so it can't separate the two. A cloud provider that is over its quota already answers HTTP 429, which maps to the retryable `ProviderRateLimited`; the router then backs off, counts the failure toward the breaker and fails over.

## Decision

`providers.rate_limit.max_requests_per_minute` defaults to **`None`, meaning no client-side throttle**. An integer (≥ 1) restores the sliding-window cap for each provider, for operators who want to stay under a known cloud quota before the provider starts returning 429s. With no cap, the router still counts requests, so `requests_in_window` in the router snapshot stays meaningful.

## Consequences

- Reasoning turns and eval runs against local backends are no longer refused by a quota that doesn't exist.
- With a cloud provider and no cap configured, the first sign of quota pressure is the provider's own 429. Retry, backoff and the circuit breaker handle it, but some requests are spent getting refused. Operators on low cloud tiers should set the cap.
- The cap is still global (one value applied to each provider). Caps set per provider would belong with the credentials config and are not needed today.
