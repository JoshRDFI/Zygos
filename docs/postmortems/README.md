# Postmortems

Write one when a bug was **subtle, systemic, and costly to rediscover**: the kind a
future contributor (human or agent) could reintroduce because nothing obvious points at
it. Routine bugs don't need one; the commit message is enough.

Each entry is one file, `YYYY-MM-DD-short-name.md`, with:

1. **Summary** — 30 seconds: what broke, who noticed, what fixed it.
2. **What happened** — the mechanism, precisely enough to recognise it again.
3. **Why every safety net missed it** — tests, reviews, types, hooks: why each let it
   through.
4. **The guard that now catches it** — the test, hook or rule, linked, and proof that it
   fails when the bug is put back.

Postmortems are history: keep them accurate to what was true at the time, and add a
dated note rather than rewriting when something changes later.

| Date | Entry |
|---|---|
| 2026-09-26 | [Stale speech transcript after a reconnect](2026-09-26-stt-desync-after-reconnect.md) |
| 2026-11-18 | [A test file emptied during an import tidy-up](2026-11-18-emptied-test-file.md) |
