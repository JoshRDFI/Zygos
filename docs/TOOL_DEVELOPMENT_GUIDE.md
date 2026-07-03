# Tool Development Guide (Phase 3)

Phase 3 introduces streaming tool execution, permission checks, parallel orchestration, and result validation.

## Building a Tool

Register tools through `BasicToolRegistry` using strict schemas.

```ts
registry.register({
  meta: {
    name: 'stream_echo',
    description: 'Streams text by chunk',
    concurrency: 'safe_parallel',
    permission: 'allow',
    retry: { attempts: 2, backoffMs: 100 }
  },
  inputSchema: z.object({ text: z.string() }),
  outputSchema: z.string(),
  async execute(input) {
    return input.text;
  },
  async *executeStream(input) {
    for (const ch of input.text) {
      yield ch;
    }
    return input.text;
  }
});
```

## Streaming Execution

Use `StreamingToolExecutor.executeBatchStream` to receive real-time events:

- `tool_started`
- `tool_progress`
- `tool_completed`

`QueryEngine` forwards these as engine events.

## Permissions

`PermissionManager` enforces:

- role-based decisions (`user`, `system`, `admin`)
- explicit deny / require approval rules
- context-aware checks from conversation tags

Denied executions are audit-logged.

## Parallel Execution

`ParallelExecutionOrchestrator` executes safe tools concurrently with:

- dependency ordering
- resource contention keys
- configurable concurrency pool
- partial failure collection

## Validation

Use `src/tools/validation.ts` for:

- schema coercion
- format checks (`json`, `text`, `binary`)
- output size limits
- sanitized normalized errors

## Error Patterns

Tool failures return normalized structured errors (no silent drops):

- `tool_not_found`
- `tool_permission_denied`
- `tool_timeout`
- `tool_execution_error`
