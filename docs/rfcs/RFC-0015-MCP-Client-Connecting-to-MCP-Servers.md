# RFC-0015: MCP Client — Connecting to MCP Servers

- **Status:** Accepted (2026-11-17)
- **Author:** Zygos maintainers
- **Created:** 2026-11-04
- **Governs:** how Zygos connects to **Model Context Protocol servers** as a client
  and offers their tools to the model: how a user adds servers (pasting the
  `mcpServers` JSON they would give Claude Desktop), how local servers are started
  and stopped, how remote servers are reached, which protocol revisions are spoken,
  how MCP tools join the RFC-0008 tool loop, how they are approved and trusted, how
  they are switched on and off, how their secrets are kept, how their results
  (including images) come back, and how all of it is shown in the Tools page,
  `zygos doctor` and the trace.
- **Depends on:**
  [RFC-0008](RFC-0008-Tool-Calling-Protocol-and-Tool-Authoring.md) (the tool
  contract, agentic loop, `tools` channel and permission resolver MCP tools go
  through),
  [RFC-0004](RFC-0004-Secret-Storage-and-Key-Entry.md) (the `SecretStore` that holds
  MCP server keys and tokens — accepted, not yet built; see Migration Plan),
  [RFC-0003](RFC-0003-Capability-Registry-Runtime-Manifest-and-Inspection.md) (the
  manifest and `zygos doctor`),
  [RFC-0007](RFC-0007-Session-Protocol-and-Turn-Loop.md) (the turn loop, the
  permission prompt over the session socket, frames), and
  [RFC-0011](RFC-0011-React-UI-Frontend-Architecture.md) (the Tools page).
- **Amends (additively):** RFC-0008 — a tool may declare its input as a **JSON
  Schema** instead of a pydantic model (§3); a tool result may carry **artifacts**
  (images, audio) beside its text (§6); a tool's permission may be raised to
  `allow` by a stored **trust** record (§5). Built-in tools are unchanged.
- **Does not govern:** Zygos acting as an MCP **server** (later, its own RFC);
  installing MCP servers or their runtimes (`node`, `uv`, Docker — the user does);
  ComfyUI itself, RunPod, or any server's own behaviour; vision input (RFC-0009).
- **Implementation status:** not started. Archon `85d6b4ab`.

## Summary

MCP is how tools are published now: filesystem, web search, ComfyUI and hundreds of
others ship as MCP servers. Zygos should use them instead of re-implementing each.
A user pastes the same `mcpServers` JSON they would give Claude Desktop; Zygos starts
the local servers itself, connects to the remote ones by address, and offers their
tools to the model through the existing tool loop. Every MCP tool **asks before it
runs until the user marks it trusted** — per tool or per server — and a tool whose
description or inputs change goes back to asking. Servers and tools can each be
switched off, and the model is only offered the ones that are on, because small local
models choose tools badly when offered dozens. Keys and tokens in the pasted JSON move
into the secret store. Images a tool returns (ComfyUI's output) are saved locally and
shown in the chat. Zygos speaks the current stateless protocol (**2026-07-28**) and
the older handshake-based revisions, because many local servers have not moved yet.

## Motivation

Zygos has a handful of built-in tools (RFC-0008) and an authoring path for more. The
tools users actually want — browse and edit files, search the web, drive ComfyUI on
this machine or on a RunPod pod they set up — already exist as MCP servers, maintained
by others, and the user already has configs for them. Writing a Zygos-native version of
each would be slow, duplicate work, and lag behind the originals.

The project's privacy meaning ("your data stays yours; internet actions are core")
fits MCP well: local servers keep files on the machine; remote servers are the user's
choice and are labelled as remote. And the project's honesty rule fits the trust
design: nothing runs without the user seeing it first, and nothing changes silently
once trusted.

## Problem Statement

1. Zygos cannot reach MCP servers at all.
2. MCP tools describe their inputs with JSON Schema; the RFC-0008 contract expects a
   pydantic model.
3. A server is code the user installed from someone else. Its tool labels
   (`readOnlyHint`, `destructiveHint`) are hints the spec says clients must not rely
   on, so Zygos needs its own trust decision — and must notice when a trusted tool
   changes.
4. Pasted configs carry API keys in `env` and `headers`; storing them as plain text
   contradicts RFC-0004.
5. The protocol changed shape in 2026-07-28 (no handshake, no sessions, per-request
   `_meta`), and most servers in the wild still speak 2025-11-25 or older.
6. Tools can return images and audio; today a tool result is text or JSON only.
7. Offering every tool from every server to a small local model makes it worse at
   picking any of them.

## Proposed Design

### 1. Adding servers: paste the JSON

The Tools page has an **Add servers** box; the CLI has `zygos mcp add` (reads a file
or stdin). Both accept the Claude Desktop shape, with or without the outer key:

```json
{ "mcpServers": {
    "filesystem": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/sage/notes"] },
    "search":     { "command": "uvx", "args": ["some-search-mcp"], "env": { "SEARCH_API_KEY": "…" } },
    "comfyui":    { "type": "http", "url": "https://<pod>.proxy.runpod.net/mcp", "headers": { "Authorization": "Bearer …" } }
} }
```

- `command` (+ `args`, `env`, `cwd`) → a **local** server Zygos starts (stdio).
- `url` (+ `headers`; `type` `"http"` or `"streamable-http"`) → a **remote** server.
  `type: "sse"` (the legacy HTTP+SSE transport, deprecated by the spec) is accepted
  with a "deprecated transport" label if the SDK still speaks it; otherwise refused
  with that reason.
- Unknown keys are kept and ignored, so a config copied from another client loads.
- A name that already exists asks before replacing it.
- **Before saving, Zygos shows what it will run**: for a local server, the exact
  command line ("This runs `npx -y @modelcontextprotocol/server-filesystem
  /home/sage/notes` on this machine as you"); for a remote one, the address. The user
  confirms. Nothing is started before that.

Servers are stored in the preferences database as an `mcp_servers` record (the same
store as `backends` and `model_choices`), not in `config.yaml`: they are user data,
added and removed at runtime. `config.yaml` may still list servers for scripted
installs; those appear read-only on the Tools page with "from config".

### 2. Secrets

Every value in `env` and every value in `headers` is treated as a secret: on save it
is moved into the RFC-0004 `SecretStore` and the record keeps a reference. The Tools
page shows only that each is set (`SEARCH_API_KEY = set`, as RFC-0004 reports
presence only — no characters of the value) and lets the user replace one.
Exported or displayed configs never contain the values. *(Treating all of them as
secret is a deliberate over-approximation: an `env` value like a directory path being
masked costs nothing; a token stored in plain text costs a lot.)*

### 3. Running servers

- **Protocol.** Zygos uses the official Python SDK (`mcp>=2,<3`, an optional
  `.[mcp]` extra), which speaks **2026-07-28** and serves every earlier revision.
  For each server Zygos detects its era as the spec describes (stdio: probe with
  `server/discover`, fall back on a non-modern error; HTTP: per the Streamable HTTP
  binding) and records it ("protocol 2026-07-28" / "protocol 2025-11-25") for the
  Tools page and doctor.
- **Local servers** start when the server is switched on (at `zygos serve` start for
  those already on), run as the user, with their `env` resolved from the secret
  store. `stderr` is captured into a bounded tail shown on the Tools page. A server
  that exits is restarted once; a second exit leaves it **stopped**, with its last
  output and exit code shown. All are stopped when Zygos stops.
- **Remote servers** are connected on use, with the stored headers.
- **Not supported** (deprecated by 2026-07-28, so not adopted): Roots, Sampling,
  Logging. Zygos declares none of them. **Elicitation** and multi-round-trip input
  requests are not supported in the first phases: Zygos does not declare the
  capability; a server that asks anyway gets a clear error the user sees in the
  trace. **Tasks** and **MCP Apps** extensions are not declared yet (later phases).
- A failing server never breaks Zygos: its tools disappear from the offered set and
  the reason is shown.

### 4. Tools from a server

- Discovered with `tools/list`, honouring `ttlMs`; refreshed on a list-changed
  notification when the server offers one (`subscriptions/listen` on 2026-07-28),
  otherwise when the Tools page is opened and before a turn if the cache is stale.
- Each becomes a Zygos tool named `<server>__<tool>` (server names are the keys the
  user pasted). Both parts are cut to `[A-Za-z0-9_-]` (other characters become `_`);
  a name over 64 characters is shortened with a short hash of the full name so it stays
  stable. A server key that would collide after this is refused at paste time with the
  reason. The name is the key for trust and on/off, so it never changes while the
  server's key and the tool's name don't. *(My call.)*
  The model sees the tool's own description, prefixed with the server name.
- **Input is the tool's JSON Schema as given** (RFC-0008 amendment): Zygos passes it
  to the provider for function calling and passes the model's arguments to the server
  unchanged; the server validates. Built-in tools keep their pydantic models.
- Timeouts: a per-server `timeout_s` (default 120 s; the Tools page shows and edits
  it), because image generation is slow.

### 5. Asking, trusting, switching off

- **Every MCP tool starts at `ask`**, whatever its annotations say. Annotations are
  shown as the server's own claims ("server says: read-only").
- **The prompt in the chat** (built in phase 1 — the backend's
  `WebSocketPromptResolver` exists, the web UI has no prompt or tool-call display
  yet): shows the server, the tool, local or remote, and the arguments, with
  **Allow once**, **Deny**, **Trust this tool** and **Trust this server**. The
  `permission_response` message gains an optional `trust: "tool" | "server"`
  (additive). The chat also shows each tool call and its result as a card. A prompt
  not answered within `server.prompt_timeout_s` is denied, as today.
- **Trust** is stored per tool or per server, from the prompt, the Tools page or the
  CLI. A trusted tool runs without asking.
- **What server trust covers:** the tools the server has when trusted. Each tool that
  appears later asks once; answering it with Allow or a trust choice stores per-tool
  trust for it. *(My call.)*
- **Trust is tied to what was trusted.** Zygos stores a fingerprint of each trusted
  tool's name, description and input schema — under server trust as well. If any of
  them changes, the tool goes back to `ask`, and the Tools page and the next prompt
  say "changed since you trusted it", with the old and new text.
- **Config rules** (`tools.permission_rules`) can only **tighten** MCP tools: a
  matching `deny` beats trust; a matching `allow` does not loosen an MCP tool —
  only trust does. Order for an MCP tool: config deny → stored trust → ask.
  *(My call: keeps "asks until you trust it" true whatever the config says.)*
- **On/off** per server and per tool. Only tools that are on are offered to the model.
  New servers' tools start **on**; the Tools page shows how many tools are on in total
  and warns above 20 ("small local models choose tools less reliably beyond about 20
  — consider switching some off"). *(20 is a starting value, adjustable later from
  eval data.)*

### 6. Results

- Text content becomes the tool result text, as today. `structuredContent` is passed
  as JSON. `isError: true` becomes a tool-error result.
- **Image and audio content** become **artifacts** (RFC-0008 amendment): saved under
  `.zygos/artifacts/<session>/<id>.<ext>` (never sent anywhere), announced on the
  `tools` channel as `tool.artifact {call_id, kind, mime, url, bytes}`, and shown in
  the chat under the tool call. The model receives a text line in place of each
  (`[image saved: comfyui__generate #1, 1024×1024]`) — sending a generated image back
  into a text model's context helps nothing and costs a lot. Size cap per artifact
  50 MB; larger ones are refused with that reason.
- **Image generation is an MCP tool, not a capability.** RFC-0003 reserves an
  `IMAGE_GENERATION` capability slot (the enum value exists in
  `runtime/capabilities.py`); with RFC-0009's `ImageGenerator` contract dropped,
  nothing binds it. It stays reserved and unused: images come from MCP tools through
  this section, and the slot is filled only if a later RFC needs a non-MCP generator.
- `resource_link` and embedded resources are shown as links/text; reading resources is
  a later phase.
- **Everything a server returns is untrusted data**, never instructions — the same
  rule the project applies to web pages (see Risks).

### 7. Seeing it

- **Tools page:** servers (status, protocol era, local command or remote address,
  last error/stderr tail, timeout), their tools (on/off, trusted/asks, changed),
  secrets masked, Add/Remove.
- **`zygos doctor`:** one line per server — running / stopped (why) / remote
  reachable / not reachable — passive for local servers (process state), a bounded
  probe for remote ones only with `--probe`.
- **Trace / Inspect:** `mcp.server` events (started, stopped, restarted, failed with
  reason) and the existing tool-call events, which name the server.
- **Manifest:** MCP tools are listed with their server and trust state; no secrets.

### 8. Changes while Zygos is running

- The server supervisor re-reads the `mcp_servers` record before each turn and when
  the Tools page changes it (cheap: one row), and starts/stops servers to match. So
  edits from `zygos mcp …` in another terminal take effect on the next turn without a
  restart.
- The **offered tool set is built per turn** from the supervisor's current view
  (servers running, tools on, list current); built-in tools are built once as today.
  The tool registry gains removal for MCP tools.
- `zygos mcp add` without a running server validates and saves only; tools are listed
  the first time `zygos serve` starts the server. `zygos mcp list` shows the tools last
  seen and when. *(My calls.)*

### 9. CLI

`zygos mcp add [FILE]`, `zygos mcp list`, `zygos mcp remove NAME`,
`zygos mcp on|off NAME[/TOOL]`, `zygos mcp trust|untrust NAME[/TOOL]`.

## Alternatives Considered

- **Trust the server's annotations by default.** Rejected (maintainer): the spec says
  they are hints; a wrong "read-only" label would run a destructive tool unasked.
- **Talk to ComfyUI's own HTTP API instead of MCP.** Rejected (maintainer): connecting
  to MCP tools generally is the goal; ComfyUI now ships an MCP server, which serves
  local ComfyUI and a RunPod pod alike.
- **Servers in `config.yaml` only.** Rejected: servers are added and removed at
  runtime from the UI; config stays available for scripted installs.
- **Write our own protocol client.** Rejected: the official SDK covers both protocol
  eras and tracks spec changes; Zygos would lag.
- **Send generated images back to the model.** Rejected for now: text models can't
  use them; vision models (RFC-0009) may later opt in.

## Migration Plan

Additive; with no servers added, behaviour is exactly today's. Phases, each its own
cycle:

0. **Secret store, the part MCP needs** — RFC-0004's `SecretStore` protocol with the
   `keyring` and `encrypted_file` backends, plus handles for MCP values
   (`mcp:<server>:env:<NAME>`, `mcp:<server>:header:<Name>`; an additive amendment of
   RFC-0004's `provider:<name>` handles) and presence-only reporting. Migrating
   provider keys and `zygos keys` stay RFC-0004's own cycle.
1. **Local and remote servers, tools, trust:** paste/CLI, the `mcp_servers` record,
   secrets moved out, stdio lifecycle, Streamable HTTP with static headers, both
   protocol eras, JSON-Schema tools in the loop, ask/trust/fingerprints, on/off, text
   results, Tools page, doctor, trace.
2. **Artifacts:** image/audio results saved and shown in chat (the ComfyUI path).
3. **Sign-in for remote servers** (OAuth per the 2026-07-28 authorization rules,
   Client ID Metadata Documents).
4. **More of MCP:** resources, prompts, elicitation / multi-round-trip input, the
   Tasks extension for long-running tools.

## Risks

- **A server is arbitrary code.** Mitigated by showing the exact command before the
  first start, `ask` by default, fingerprinted trust, and per-tool off switches. Zygos
  does not sandbox servers (out of scope; stated on the Add screen).
- **Prompt injection through tool output or tool descriptions** (a web page or file
  telling the model to call another tool). Mitigated by `ask` on untrusted tools, the
  prompt showing real arguments, results framed as data, and no tool being trusted by
  default. It is not eliminated, and the docs say so.
- **Spec churn.** Mitigated by the SDK and by recording each server's era.
- **Slow or hung servers.** Per-server timeouts, bounded stderr, a single restart.
- **Too many tools.** On/off switches and the count warning.

## Acceptance Criteria

1. Pasting a Claude Desktop `mcpServers` JSON (with or without the outer key) adds
   its servers after a confirmation that shows each local command line or remote
   address; unknown keys are ignored; a duplicate name asks first.
2. `env` and `headers` values are stored only in the secret store; the record, the
   manifest, the Tools page and any export never contain them.
3. A local server is started on enable and on serve start, restarted once on exit,
   and left stopped with its stderr tail and exit code after a second exit; all are
   stopped on shutdown.
4. Zygos connects to a 2026-07-28 server and to a 2025-11-25 server (both proven with
   test servers) and reports each one's era.
5. MCP tools appear as `<server>__<tool>`, are offered only when on, take their JSON
   Schema input unchanged, and run through the RFC-0008 loop.
6. An untrusted MCP tool always asks; trusting it (or its server) lets it run
   unasked; changing its description or schema returns it to `ask` with the change
   shown; a new tool under a trusted server asks once.
   The chat shows the prompt (Allow once / Deny / Trust this tool / Trust this
   server) and each tool call as a card; a config `deny` beats trust and a config
   `allow` does not loosen an MCP tool.
6a. An edit made with `zygos mcp …` while `zygos serve` runs takes effect on the next
   turn without a restart.
7. An image result is saved under `.zygos/artifacts/`, shown in the chat, announced
   as `tool.artifact`, and replaced by a text line in the model's context (phase 2).
8. A crashed, unreachable or erroring server removes only its own tools and shows why
   on the Tools page, in doctor and in the trace; turns keep working.
9. With no servers added, every existing test and behaviour is unchanged.

## Architectural Impact

- **Coupling.** One new package (`zygos/mcp/`) that registers tools into the existing
  `ToolRegistry`; the agentic loop and permission resolver are reused, not forked.
- **Hidden state.** None: servers, trust and on/off live in the preferences store and
  are shown on the Tools page; processes and failures emit events.
- **Service boundaries.** MCP tools are tools; nothing outside the tool layer knows
  where a tool came from beyond its name and server label.
- **New service?** A server supervisor inside `zygos/mcp/` (process lifecycle), owned
  by the runtime assembly and closed with it. No new long-lived service elsewhere.
- **Removability.** Remove the extra and the package; built-in tools are unaffected.
