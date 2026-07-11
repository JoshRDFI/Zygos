# RFC-0006: Embedding Contract and Hybrid Memory Retrieval

- **Status:** Draft (2026-07-11)
- **Author:** Zygos maintainers
- **Created:** 2026-07-11
- **Governs:** the `Embedder` service contract, the `EMBEDDING` capability, how
  memory records and queries are turned into vectors, where vectors are stored,
  how lexical (FTS5) and semantic (vector) signals are fused into a relevance
  score, and when embedding work runs relative to the durable write path
- **Depends on:**
  [RFC-0001](RFC-0001-Service-Architecture.md) (the `MemoryService` interface §2,
  the layering/dependency rule §1, explicit state objects §4),
  [RFC-0002](RFC-0002-Runtime-Event-Bus-and-ExecutionContext.md) (the
  single-event-loop concurrency model and the "never block the loop" spirit, and
  the load-bearing *puller* invariant — resolution/observability that depends on
  no subscriber), and
  [RFC-0003](RFC-0003-Capability-Registry-Runtime-Manifest-and-Inspection.md)
  (the closed capability set §1, plugin self-declaration §2, contract-validated
  registration and health-ranked resolution §3, and the manifest §5). This RFC
  **amends RFC-0003's closed capability set** by adding one member and one
  contract entry. It **extends the M4 memory subsystem** (the `RelevanceIndex`
  seam that `Fts5RelevanceIndex` was built to hand off).
- **Notably does *not* amend RFC-0001's `Provider` contract** — see §1 and
  Architectural Impact.
- **Implementation status:** tracked in [ROADMAP.md](../../ROADMAP.md); this RFC
  locks the design, and the work lands as its **own build cycle before M8**, so
  the M8 turn loop is built against the final retrieval shape rather than
  reworking a lexical-only one.

## Summary

Give Zygos **semantic memory retrieval**. Add a small `Embedder` service contract
— a *separate* contract from `Provider`, not a method on it — and an `EMBEDDING`
capability that binds to it. Memory records are embedded by a **deferred
background pass** (`embed_backlog`) so the durable write path stays cheap,
synchronous, and provider-independent, exactly as M4 requires. Retrieval fuses the
existing FTS5 lexical signal with vector similarity by **Reciprocal Rank Fusion**
behind the already-built `RelevanceIndex` seam, degrading cleanly to lexical-only
when no embedder is configured. Vectors are stored as a **BLOB column in the
existing SQLite store** and searched by **brute-force cosine** — right-sized for
personal-agent memory, with `sqlite-vec` named as a drop-in ANN seam behind the
same Protocol. Embeddings **default to running locally** (an in-process CPU model
by default, Ollama as an alternative), fully **decoupled from the chat provider**,
so a deployment using a cloud chat model spends **no** tokens and burns **no** GPU
on embeddings unless it explicitly opts in.

## Motivation

M4 shipped a layered memory system whose retrieval is lexical-only: `retrieve()`
ranks candidates from an FTS5 index blended with recency and importance. Lexical
matching cannot find memory by *meaning* — "the deployment kept crashing" will not
surface a record that says "the service OOM-looped on boot." Semantic recall is
the point of an agent memory, and M4 anticipated it: the retrieval layer already
routes every relevance lookup through a pluggable `RelevanceIndex` Protocol, and
`Fts5RelevanceIndex`'s own comment states that "the embedding/hybrid increment
replaces this." This RFC is that increment.

It must land **before M8**. M8 is the first consumer of `MemoryService`; building
the turn loop against a lexical-only retrieval shape and then swapping in the
semantic one would rework the turn loop twice. Locking the retrieval contract now
— including the one change that ripples outward, `retrieve()` becoming async — is
the whole reason the milestone order puts this increment ahead of M8.

Two forces shape the design beyond "add embeddings." First, M4's **cheap,
synchronous, durable episodic write** is an invariant worth keeping: storing a
memory must not await a provider or fail when one is down. Second, embeddings are
**high-volume, low-value-per-call** work — one vector per stored record and one
per query — so routing them to a metered cloud API is the wrong default. The
design keeps both: embedding is deferred off the write path, and it runs locally
by default regardless of which provider answers chat.

## Problem Statement

1. **No way to turn text into a vector.** The runtime has a `Provider` contract
   for chat generation and nothing for embeddings. Semantic retrieval is
   impossible until a satisfier contract exists.
2. **`Provider` is the wrong home for it.** Anthropic ships no embeddings API;
   putting `embed()` on `Provider` forces a dead, raising method onto at least one
   shipping provider. Worse, `CAPABILITY_CONTRACTS` already maps
   `LOCAL_INFERENCE → Provider`; a second capability bound to the same contract
   would make RFC-0003 §3's `isinstance` check pass for a provider that cannot
   embed, so the contract would no longer *prove* the capability.
3. **Embedding is async; two M4 paths are synchronous.** M4's `store()` is
   sync/durable/no-await and `retrieve()`/`search()` are sync. Embedding a record
   or a query is an async provider call. Naïvely embedding on the write path
   reintroduces a provider dependency and failure mode onto durable writes;
   semantic retrieval cannot be expressed without an await somewhere.
4. **Lexical and semantic scores are not comparable.** FTS5 rank and cosine
   similarity live on different scales; a naïve weighted sum needs per-corpus
   tuning and drifts. Fusion must be robust without a magic constant.
5. **Cloud embedding is a silent cost trap.** If the embedder were tied to the
   chat provider, a user on a cloud chat model would pay per-token for every
   memory write and every query, and — if the embedder used the GPU — contend for
   VRAM with inference. Neither should happen by default.
6. **The feature must be removable and degrade cleanly.** A deployment with no
   embedder configured, or one missing the optional dependency, must behave
   exactly as M4 does today, not fail.

## Proposed Design

### 1. The `Embedder` contract — separate from `Provider`

A new, small service contract (RFC-0001 §2 layering — a provider-tier contract,
peer to `Provider`, not a superset of it):

```python
@runtime_checkable
class Embedder(Protocol):
    name: str
    async def embed(self, request: EmbedRequest) -> EmbedResult: ...
```

```python
class EmbedRequest(BaseModel):        # frozen, extra="forbid"
    texts: tuple[str, ...]            # batch-first: the backlog pass embeds many;
                                      # the query path sends a one-element batch

class EmbedResult(BaseModel):         # frozen, extra="forbid"
    vectors: tuple[tuple[float, ...], ...]   # aligned 1:1 with request.texts
    model: str                        # the embedding model that produced them
    dim: int                          # vector dimensionality
    usage: Usage = Usage()            # reuses the provider Usage model
```

**`embed` is async by contract, and that is load-bearing** (§6): it lets an
HTTP-backed embedder `await` network I/O *and* lets an in-process CPU embedder
offload its synchronous, CPU-bound work to a worker thread, so neither blocks the
single event loop (RFC-0002).

**This RFC does not touch `Provider`.** A chat backend that can also embed
(Ollama, OpenAI, vLLM) implements *both* `Provider` and `Embedder` structurally;
Anthropic implements only `Provider`; a pure embedding backend implements only
`Embedder`. This is the direct payoff of a separate contract — reality is modeled
without a lying method, and the two capabilities stay distinguishable.

### 2. The `EMBEDDING` capability (amends RFC-0003 §1)

One member is added to the closed capability set, and one entry to the contract
map:

```python
class Capability(StrEnum):
    ...                                     # the existing eight, unchanged
    EMBEDDING = "embedding"

CAPABILITY_CONTRACTS: Mapping[Capability, type] = {
    Capability.LOCAL_INFERENCE: Provider,
    Capability.EMBEDDING: Embedder,         # added by this RFC
}
```

Because the contract is `Embedder` (not `Provider`), RFC-0003 §3's
contract-validated `register()` now *proves* the capability: a backend that
declares `EMBEDDING` but does not implement `embed()` is rejected at the Register
Capabilities stage, and Anthropic — which does not implement `Embedder` — simply
never declares it. Embed-capable plugins self-declare it exactly as RFC-0003 §2
prescribes:

```python
class OllamaProvider:
    name = "ollama"
    capabilities = frozenset({Capability.LOCAL_INFERENCE, Capability.EMBEDDING})
```

**Backend matrix:**

| Backend | `Provider` | `Embedder` | Default role for embedding |
|---|:--:|:--:|---|
| in-process local (fastembed/ONNX) | — | ✓ | **default embedder** |
| ollama | ✓ | ✓ | local alternative (config-selected) |
| openai | ✓ | ✓ | cloud, **opt-in only** |
| vllm | ✓ | ✓ | cloud/self-hosted, opt-in only |
| anthropic | ✓ | — | never (no embeddings API) |
| fake | ✓ | ✓ | deterministic test embedder |

**Registry integration mirrors LOCAL_INFERENCE's current status.** `EMBEDDING`
bindings are registered so they appear in the manifest, `zygos inspect`, and
`zygos doctor` ("who provides Embedding, and is it healthy?"). But — exactly as
`ModelService` is wired direct-from-router today while the registry declares
`LOCAL_INFERENCE` — `MemoryService` receives a **directly injected `Embedder`**
that bootstrap resolves once by config priority (§7). The registry is for
declaration and inspection; it is not yet the load-bearing resolution path. This
keeps the coupling story identical to M3/M4 and adds no new runtime dependency on
the registry.

### 3. Vector storage — BLOB column, brute-force cosine

Vectors live in the **existing SQLite/WAL store** (M4), added by an additive
migration through M4's migration framework:

```sql
CREATE TABLE memory_embedding (
    record_id TEXT PRIMARY KEY REFERENCES memory_record(id) ON DELETE CASCADE,
    model     TEXT NOT NULL,     -- the embedding model that produced the vector
    dim       INTEGER NOT NULL,
    vector    BLOB NOT NULL      -- float32, little-endian, dim*4 bytes
);
```

Nearest-neighbor is **brute-force cosine** computed in Python (numpy) over
candidate vectors. For personal-agent memory — thousands to tens of thousands of
records — a full scan is a few milliseconds; the retrieval already loads and
scores candidates by recency/importance, so this is proportionate, not a
bottleneck. numpy ships as an optional **`embeddings` extra** (the RFC-0004
optional-extras precedent), pulled in only when embedding is used.

**Model-change correctness.** A vector is only comparable to another produced by
the *same* embedding model. Each row is tagged with `model` + `dim`; vector search
filters to the **active** embedding model. A row whose stored vector is from a
different model is treated as **unembedded** (re-embedded by the backlog pass,
§4). Cosine is never computed across models — that would be silent garbage.

**ANN is a future seam, not this RFC.** `sqlite-vec` (or an equivalent) can later
replace the brute-force scan behind the **same `RelevanceIndex` Protocol** with no
contract change; it is deferred because it adds a compiled loadable extension for
scale Zygos does not have. The Protocol boundary is what makes the swap free.

### 4. Write path — deferred embedding pass

`store()` is **unchanged**: synchronous, durable, no await, no provider
dependency. A stored record simply has no `memory_embedding` row yet — the write
invariant M4 established is preserved verbatim.

Embedding runs as a **deferred pass**, structurally identical to M4's deferred
consolidation cursor:

```python
async def embed_backlog(self, ctx: ExecutionContext) -> int: ...
```

- Selects records that lack a current-model vector (the "unembedded" set: no row,
  or a row tagged with a superseded model).
- Embeds them in batches via the injected `Embedder` (`embed_batch_size`).
- Backfills `memory_embedding` rows.
- Returns the count embedded.

It is **idempotent, resumable, and crash-safe**: an interrupted pass leaves the
still-unembedded records to be picked up next time — the same "no experience is
lost" property as the `consolidated=0` cursor. It is one member of the async
family alongside `summarize`/`flush`/`resume`. M8 drives it on a cadence and at
`resume()` (startup); because embedding is deferred, it naturally runs **during
lulls**, not on the critical path of a turn. When the injected embedder is `None`,
`embed_backlog` is a no-op that returns 0.

### 5. Read path — async hybrid retrieval

**`retrieve()` becomes async** (and `search()` with it, for a uniform contract).
`MemoryService` owns query embedding; callers never pre-embed. This is a change to
the `MemoryService` surface, made now precisely because it has **no consumer yet**
— M8 is the first, and it awaits everything — so the cost is zero now and a rework
later.

The fusion lives behind the existing seam. The `RelevanceIndex.query` Protocol
becomes `async`; `Fts5RelevanceIndex` gains a trivially-async `query` (no await
inside), and a new index composes the two arms:

```python
class HybridRelevanceIndex:                 # implements RelevanceIndex
    def __init__(self, fts, vector, embedder): ...
    async def query(self, text: str, *, k: int) -> list[tuple[str, float]]:
        qvec = (await self._embedder.embed(EmbedRequest(texts=(text,)))).vectors[0]
        lexical  = await self._fts.query(text, k=k)     # ranked ids
        semantic = self._vector.search(qvec, k=k)       # cosine-ranked ids
        return rrf_fuse(lexical, semantic, k=k)         # → [(id, relevance∈(0,1])]
```

**Reciprocal Rank Fusion** combines the two arms by *rank*, not score:
`score(id) = Σ_arm 1/(K + rank_arm(id))` (K ≈ 60), normalized so the top result is
1.0. RRF is scale-agnostic — it never has to reconcile FTS5 rank magnitude with
cosine magnitude — and needs no per-corpus tuning. The fused value is the
`relevance` term the M4 `MemoryRetriever` already blends with recency and
importance; that multi-factor scoring, its weights, and its token budgeting are
**unchanged**. Only the source of `relevance` improves.

**Retrieval mode is config-selected and degrades cleanly:**

| `retrieval_mode` | Index used | Behavior |
|---|---|---|
| `fts5` (default) | `Fts5RelevanceIndex` | today's lexical retrieval, unchanged |
| `vector` | vector-only index | pure cosine (mainly for evaluation) |
| `hybrid` | `HybridRelevanceIndex` | RRF of both — the recommended semantic mode |

If `hybrid`/`vector` is configured but **no embedder resolves** (extra not
installed, no local backend, no opted-in cloud route), retrieval **degrades to
FTS5 with a single loud warning** (the RFC-0004 loud-degradation precedent) rather
than failing. And retrieval is **advisory, not load-bearing**: a transient embed
failure *during* a `retrieve()` call falls back to the lexical arm for that call
and never raises into the turn.

### 6. Local-first embedding, decoupled from chat

The embedder is chosen by a **distinct config selector**, never inherited from the
chat route. Chat on OpenAI does not drag embeddings to OpenAI.

- **Default is local.** Two local backends ship; the default is the **in-process
  CPU embedder** (fastembed/ONNX — no torch, so it stays light and droplet-viable;
  a small model such as a `nomic`/`bge-small` ONNX is fetched once and cached).
  **Ollama** (`nomic-embed-text`) is available by config for deployments already
  running Ollama that prefer to reuse it. The capability registry ranks multiple
  `EMBEDDING` satisfiers by config priority, so "prefer local, then …" is just
  ordering.
- **Cloud is opt-in only.** `openai`/`vllm` embedders remain in the contract for
  flexibility but are **never** selected implicitly. No embedding tokens are spent
  unless a cloud embedding route is explicitly configured.
- **The event loop stays responsive.** The in-process embedder's `embed()`
  offloads its CPU-bound work via `asyncio.to_thread`, honoring RFC-0002's
  single-loop model. Because embedding is deferred to lulls (§4) and CPU-only by
  default, it neither blocks a turn nor contends for the GPU the LLM manages —
  directly relevant to the VRAM-contention constraint that also drives RFC-0005.

### 7. Configuration and bootstrap wiring

This extends M4's existing (config-gated, default-OFF) memory wiring; it adds no
new subsystem wiring.

- `MemoryConfig` gains: `retrieval_mode: Literal["fts5","vector","hybrid"] =
  "fts5"`, an embedding backend selector + model reference (default: the local
  in-process backend), and `embed_batch_size`.
- At bootstrap, when `retrieval_mode` needs an embedder, the composition root
  resolves the highest-priority healthy `Embedder` and injects it into
  `DefaultMemoryService` and the `HybridRelevanceIndex`. It also registers the
  `EMBEDDING` capability binding(s) for manifest/doctor visibility (§2).
- The whole feature stays **default-OFF**: a runtime with no embedding config
  behaves exactly as M4 does today.

### 8. Observability — pull-only, no new events

Consistent with M4 and M5, embedding adds **no bus events** and preserves
RFC-0002's puller invariant. `MemoryState` (the existing pull-only snapshot) gains
counts for embedding progress: how many records are embedded vs. pending, and the
active embedding model. This is the inspection surface M8/TraceService renders;
per-record embedding events, if ever wanted, are deferred to a future
TraceService-consumer RFC — the same deferral M4/M5 made for their `*.` taxonomies.

## Alternatives Considered

- **`embed()` on the `Provider` contract (amend RFC-0001).** Rejected. It forces
  a dead, raising method onto Anthropic, and — because `LOCAL_INFERENCE` already
  binds to `Provider` — it breaks RFC-0003 §3's guarantee that the contract check
  proves the capability. A separate `Embedder` models reality and keeps the two
  capabilities distinguishable, at the cost of one more small Protocol (cheap).
- **Embed on the write path (`store()` awaits the embedder).** Rejected. It
  reintroduces a provider dependency and failure mode onto M4's durable,
  synchronous write — a memory write could block or fail because an embedder is
  down. The deferred pass keeps writes cheap and never loses an experience.
- **Embed only at consolidation.** Rejected. Only consolidated/semantic records
  would get vectors, leaving recent un-consolidated episodic memory ("what did I
  just do") semantically invisible. The backlog pass covers all records.
- **Pure vector retrieval (drop FTS5).** Rejected. Embeddings blur exact tokens —
  IDs, code, tool-error strings, rare proper nouns — which memory stores and which
  users query precisely. Hybrid keeps lexical precision *and* semantic recall.
- **Weighted-sum fusion of BM25 + cosine.** Rejected. The two scores are on
  incomparable scales; the blend needs per-corpus tuning and drifts. RRF fuses
  ranks and sidesteps the problem with no magic constant.
- **Embedding tied to the chat provider.** Rejected. It would spend cloud tokens
  on every memory write and query for a cloud-chat user, and risk GPU contention.
  Local-by-default, decoupled selection, costs nothing and contends for nothing.
- **sqlite-vec / a native ANN index now.** Deferred, not rejected. It adds a
  compiled loadable extension for scale Zygos does not have. Brute-force cosine is
  correct at personal-agent scale, and the `RelevanceIndex` Protocol makes the ANN
  swap a drop-in when scale demands it.
- **An external vector database (Chroma/FAISS/Qdrant).** Rejected. A new process
  to run, secure, and back up — against the single-file-SQLite grain and the
  local/droplet deployment model. Overkill for the scale.
- **Keep `retrieve()` sync; add an async sibling / push query-embedding to the
  caller.** Rejected. Two retrieval APIs make the *best* path the awkward one, and
  pushing query embedding to callers leaks retrieval's responsibility outward and
  couples M8 to embeddings. With no consumer yet, making `retrieve()` async is
  free and keeps one clean contract.

## Migration Plan

Purely additive; nothing to migrate away from.

1. Add the `Embedder` contract and the `EMBEDDING` capability + contract entry.
2. Retrofit the embed-capable providers (Ollama, OpenAI, vLLM, fake) with
   `embed()` and the `EMBEDDING` declaration; add the in-process local embedder.
3. Add the `memory_embedding` table via an additive migration; existing FTS rows
   keep working untouched.
4. Turn `RelevanceIndex.query`, `MemoryRetriever.retrieve`, and the
   `MemoryService` `retrieve`/`search` methods async; add `HybridRelevanceIndex`
   and `embed_backlog`. `retrieve()` sync→async is a free change — the surface is
   Experimental (COMPATIBILITY.md) with **no** current consumer.
5. Wire `MemoryConfig` (`retrieval_mode`, embedding backend, batch size) and
   bootstrap resolution/injection; register the `EMBEDDING` binding for
   inspection.
6. First `embed_backlog` run backfills vectors for pre-existing records.

A deployment that sets nothing behaves exactly as M4 does today: `retrieval_mode`
defaults to `fts5`, no embedder is resolved, `embed_backlog` is a no-op.

## Risks

- **`retrieve()` sync→async ripples to any caller.** *Mitigation:* there is no
  caller yet — M8 is the first, and it is async. Doing this before M8 is the point
  of the milestone ordering.
- **Optional dependency missing at runtime.** `hybrid` configured without the
  `embeddings` extra or any embedder. *Mitigation:* loud one-time degrade to FTS5;
  `zygos doctor` reports embedding unavailable and why.
- **Embedding-model change invalidates stored vectors.** *Mitigation:* vectors are
  model-tagged; search filters to the active model; superseded vectors are treated
  as unembedded and re-embedded by the backlog pass. No cross-model cosine.
- **In-process CPU embedding blocks the event loop.** *Mitigation:* `embed()`
  offloads to a worker thread (`asyncio.to_thread`); work is deferred to lulls and
  batched.
- **Brute-force cosine outgrows its scale.** *Mitigation:* proportionate at
  personal-agent scale; `sqlite-vec` is a drop-in behind the same Protocol when a
  deployment's record count justifies it. `MemoryState` counts make the growth
  observable.
- **Transient embed failure during retrieval.** *Mitigation:* retrieval is
  advisory — a failed query embedding falls back to the lexical arm for that call
  and never raises into the turn.
- **First-run model fetch for the local embedder.** *Mitigation:* small ONNX
  model, cached after first use; the offline/pre-seed and doctor-reporting posture
  mirrors RFC-0005's provisioning stance.

## Acceptance Criteria

1. An `Embedder` that declares `EMBEDDING` **registers**; one that does not
   implement `embed()` is **rejected** at the Register Capabilities stage; the
   Anthropic provider **does not** satisfy `EMBEDDING`.
2. `store()` remains synchronous and writes **no** embedding row; a memory write
   succeeds with no embedder configured and with the embedder down.
3. `embed_backlog` embeds all unembedded records, is a **no-op on a second run**
   with no new records, and — interrupted mid-pass — leaves the remainder embedded
   on the next run (idempotent, resumable).
4. After the embedding model changes, records tagged with the old model are
   **re-embedded**, and vector search returns **no** cross-model matches.
5. On a semantic-recall fixture (query and record share meaning but few words),
   `hybrid` retrieval surfaces the record where `fts5` does not; on an
   exact-token fixture, `hybrid` still surfaces the lexical match.
6. With `retrieval_mode=hybrid` and no embedder resolvable, retrieval **degrades
   to FTS5** with one warning and does **not** fail; a transient query-embed
   failure falls back to lexical for that call without raising.
7. Embeddings run on the **configured local backend** while chat runs on a
   **cloud** provider, spending **zero** embedding tokens on the cloud chat
   account.
8. `retrieve()` and `search()` are async; the M4 multi-factor blend (relevance ·
   recency · importance) and token budgeting produce the same selection given the
   same relevance inputs.
9. The runtime manifest and `zygos doctor` report the active embedding backend and
   whether `EMBEDDING` is available and healthy; `MemoryState` reports
   embedded-vs-pending counts.
10. With no embedding configuration, the runtime behaves **identically to M4**
    (`fts5`, no embedder, `embed_backlog` a no-op).

## Architectural Impact

- **Coupling.** Adds one provider-tier contract (`Embedder`) peer to `Provider`,
  and one capability→contract entry. `MemoryService` gains a directly injected
  `Embedder` — the same injection shape `ModelService` already uses — so it takes
  on **no new dependency on the capability registry**. The registry gains an
  `EMBEDDING` binding for declaration/inspection only.
- **Does it amend a prior contract?** It **amends RFC-0003's closed capability
  set** (one member + one contract entry) — a change RFC-0003 §1 explicitly
  reserves for a future RFC. It **evolves the Experimental `MemoryService`
  surface** (`retrieve`/`search` → async; new `embed_backlog`). It **does not
  amend RFC-0001's `Provider` contract** — the reason the `Embedder` contract is
  separate.
- **Hidden state.** Vectors are visible at the service boundary: embedded-vs-
  pending counts and the active model are in the pull-only `MemoryState` snapshot,
  and `EMBEDDING` availability/health is in the manifest and `zygos doctor`. No
  state the console cannot see.
- **Event bus.** No new events; resolution and observability stay **pull-only**,
  preserving RFC-0002's load-bearing puller invariant. A future TraceService
  consumer may add an embedding taxonomy — deferred, as M4/M5 deferred theirs.
- **Service boundaries.** No boundary is bypassed. This RFC fills the
  `RelevanceIndex` seam M4 built for exactly this hand-off and honors RFC-0002's
  single-loop model (thread-offloaded local embedding; deferred backlog pass).
- **Constitution.** Local-first (embeddings default local, decoupled from chat),
  inspectable (nothing magical — declared capability, snapshotable progress,
  doctor-visible), and honest (no dead method on Anthropic; no silent cross-model
  cosine; loud degradation).
- **Independent testability.** `Embedder` is mockable (the `fake` embedder is
  deterministic); `HybridRelevanceIndex` and RRF are unit-testable with fixed
  arms; `embed_backlog` is testable against the store with a fake embedder; the
  degrade-to-FTS path is testable with no embedder.
- **New service?** No new runtime service. A new *contract* and a capability;
  embedders are plugins behind it, and the memory subsystem consumes one by
  injection.
- **Removable?** Yes. With `retrieval_mode=fts5` and no embedder, the entire
  feature is inert and the runtime core is exactly M4.
