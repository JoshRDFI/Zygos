# Context Management Guide (Phase 4)

## Overview
Phase 4 adds persistent, searchable, budget-aware conversation context.

## Components
- `ContextManager`: primary orchestration API.
- `SQLiteContextStorage`: durable storage + migrations + FTS5 index.
- `TokenBudgetSystem`: budget planning and usage analytics.
- `ContextCompactor`: compacts stale turns into summary turns.
- `ContextSearch`: FTS retrieval wrapper.

## Key workflows
1. `prepare(input, model)`
   - loads recent turns
   - retrieves memory by FTS query
   - computes token budget/window
   - triggers compaction if threshold exceeded
2. provider/tool execution
   - provider sees selected context in prompt
   - tools receive snapshot + facts in execution context
3. `postTurnUpdate(...)`
   - writes user + tool + assistant turns
   - extracts long-term memory facts
   - updates budget history and invalidates cache

## CLI history search
```bash
npm run dev -- --history-search "database backup" --session session_123
```

## Storage operations
- Database path default: `.zygos/context.db`
- Override path with env var:
```bash
ZYGOS_CONTEXT_DB=/tmp/zygos-context.sqlite npm run dev -- "hello"
```
- Programmatic backup/restore via `ContextManager.backupDatabase()` / `restoreDatabase()`.

## Testing coverage
- storage persistence + FTS queries
- budget planning/reporting
- compaction behavior with tool-result preservation
- engine integration for automatic persistence and search
