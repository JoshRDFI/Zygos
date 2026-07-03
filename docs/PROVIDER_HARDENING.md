# Provider System Hardening Guide (Phase 2.1)

## Architecture overview

```text
User turn
  -> QueryEngine
    -> ProviderRouter(plan + score)
      -> rate limiter check
      -> circuit breaker check
      -> request token estimate/cache
      -> provider.stream(request)
         -> request validation/sanitization
         -> secure endpoint checks (HTTPS or localhost HTTP)
         -> timeout-bounded fetch
         -> response schema validation
      -> retry/backoff for transient failures
      -> fallback activation
      -> graceful degradation message if all routes fail
```

## What was hardened

- Structured logs with redaction (`StructuredLogger` + `redactSensitive`).
- Typed request/response schemas for provider payloads.
- Stream robustness checks (partial stream and malformed frame handling).
- Retry decisions now use transient error detection.
- Router-level rate limiting and provider performance metrics.
- Circuit breaker state transition logs (open/half-open/closed).
- Graceful degradation output when all providers fail.
- Config-level validation for retry/rate-limit/circuit-breaker limits and duplicate fallback routes.
- Config migration support from legacy `provider` -> `providers` block.

## Error codes

| Code | Meaning | Typical Action |
|---|---|---|
| `recoverable_provider_error` | Generic provider/network failure | Retry and/or fallback |
| `network_timeout` | Request exceeded timeout | Retry with backoff |
| `malformed_response` | Provider returned invalid/empty payload | Retry or switch provider |
| `rate_limited` | Provider/user exceeded request rate | Backoff, lower QPS |
| `authentication_error` | Missing/invalid API credentials or insecure endpoint | Fix credentials/config |
| `provider_unavailable` | Provider returned 5xx or truncated stream | Fallback provider |
| `budget_exhausted` | Token/request-size constraints exceeded | Reduce prompt/output |
| `tool_contract_error` | Tool contract violation | Fix tool schemas or outputs |
| `permission_denied` | Tool policy denies execution | Adjust policy/permissions |
| `fatal_runtime_error` | Non-recoverable runtime issue | Surface and abort turn |

## Configuration options (provider hardening)

```yaml
providers:
  retry:
    maxAttempts: 3
    baseDelayMs: 400
    maxDelayMs: 5000
    jitterRatio: 0.2
  circuitBreaker:
    failureThreshold: 3
    resetTimeoutMs: 30000
    halfOpenMaxRequests: 1
  rateLimit:
    maxRequestsPerMinute: 120
    burst: 20
  observability:
    debug: false
  gracefulDegradationMessage: "All model providers are currently unavailable. Please retry in a moment."
  credentials:
    openai:
      apiKey: ${OPENAI_API_KEY}
      requestSizeLimitBytes: 1048576
      requireApiKey: true
```

## Fallback chain behavior

1. Router ranks eligible routes from `primary + fallbacks`.
2. For a selected route, retries transient errors with exponential backoff.
3. On retry exhaustion or non-transient failure, router activates next healthy fallback.
4. Circuit breaker blocks repeatedly failing routes until cooldown.
5. If all routes are exhausted, router returns configured graceful-degradation message.

## Provider integration checklist

1. Extend `BaseProvider`.
2. Add strict response schema(s) in `src/providers/schemas.ts`.
3. Validate/sanitize request via `validateAndSanitizeRequest`.
4. Use `postJson` / `fetchWithTimeout` helpers.
5. Emit `ProviderStreamEvent` with `done` on completion.
6. Add adapter and router tests.

## Troubleshooting

### "Route skipped due to missing credentials"
- Ensure `apiKey` is configured or environment variable is exported.
- Verify `requireApiKey` for local providers (Ollama/vLLM should usually be `false`).

### "Refusing insecure non-local endpoint"
- Use `https://` for remote endpoints.
- Plain `http://` is only allowed for `localhost` and `127.0.0.1`.

### Frequent fallback activation
- Check provider latency/availability metrics in logs.
- Increase timeout (if network is slow) or reduce request size.
- Tune circuit breaker and retry policy.

### Rate-limited errors
- Lower request concurrency.
- Tune `providers.rateLimit` and external provider quotas.
