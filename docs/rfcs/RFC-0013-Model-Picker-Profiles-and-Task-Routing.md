# RFC-0013: Model Picker, Model Profiles, and Best-Model-Per-Task Routing

- **Status:** Accepted (2026-11-04)
- **Author:** Zygos maintainers
- **Created:** 2026-11-04
- **Governs:** how Zygos knows what each model can do and whether it fits the
  machine (**model profiles** and a **hardware scan**); how the user picks, downloads
  and sets a default model from the web app without editing config or restarting
  (the **model picker**); and how Zygos picks the best model for a turn — by
  **suggesting** a better model after the answer, or, when the user opts in,
  **switching automatically** — including loading and unloading local models
  (**residency**).
- **Depends on:**
  [RFC-0001](RFC-0001-Service-Architecture.md) (the `Provider`/`ModelService`
  contract §2 this RFC makes load-bearing),
  [RFC-0002](RFC-0002-Runtime-Event-Bus-and-ExecutionContext.md) (trace events),
  [RFC-0003](RFC-0003-Capability-Registry-Runtime-Manifest-and-Inspection.md) (the
  runtime manifest and `zygos doctor`),
  [RFC-0007](RFC-0007-Session-Protocol-and-Turn-Loop.md) (the turn loop and frame
  set this RFC extends),
  [RFC-0010](RFC-0010-User-Personalization-and-Assistant-Identity.md) (the local
  preferences store the saved default lives in), and
  [RFC-0012](RFC-0012-Native-Thinking-Controls.md) (the re-ask pattern the
  suggestion reuses, and the Ollama `/api/show` probe).
- **Takes over from** [RFC-0009](RFC-0009-Vision-Input-Images-and-PDFs.md)
  (still a Draft): its §1 (the session is the context; the authoring model is per
  turn), §2 (load-bearing `ModelService` selection), §4 Path C (text-specialist
  routing), §6 (model residency) and §7 (context fit), and the hardware-feasibility
  scoring it deferred to "the model-picker RFC". RFC-0009 keeps vision input, image
  generation and backend placement, and depends on this RFC for selection and
  residency.
- **Amends:** RFC-0001 §2 additively (an optional `route` on `generate`/`stream`, as
  RFC-0009 §2 proposed); RFC-0007 §2 additively (new frame types and optional
  fields; older clients ignore them); RFC-0010's store is untouched (a separate `model_choices` record sits beside it).
- **Does not govern:** remote or rented compute (Archon `b73b0912`), MCP (Archon
  `85d6b4ab`, deferred), vision and image generation (RFC-0009), installing Ollama
  itself (the installer RFC).

## Summary

Each model gets a **profile**: a JSON file recording what it can do, how big it is,
how fast it runs here, and how well it does at kinds of task, with every value
labelled by where it came from (Ollama, the model file, Zygos's own measurements, an
eval run, or the user — the user's edits always win). A **hardware scan** plus the
profile tells Zygos whether a model fits: on the GPU, partly on the GPU, or not at
all. The web app's Models page becomes a **picker**: list installed models with their
fit, set a saved default (no restart), and download new ones after a fit check. For
each turn, Zygos classifies the request and, if a fitting model's profile is clearly
better at that kind of task, **offers "Ask <model>" after the answer** — a re-ask,
like "Think it through". An **opt-in auto-switch** mode picks before answering
instead, with a visible "loading <model>…" notice. Every decision is traced.

## Motivation

Today the model is a line in the config file; changing it means editing YAML and
restarting the server. No single model is best at everything: in the maintainer's
own comparison (Archon `4fd8129d`), gemma4 scored 7/7 on code where qwen3.5 scored
0/7, while qwen3:8b was fastest for chat. LM Studio shows that telling people up
front which models their machine can run is valuable; Zygos should do the same, and
go further by using what it learns about each model to route work.

## Problem Statement

1. Changing the model needs a config edit and a restart.
2. Nothing tells the user whether a model fits their GPU before they pull it.
3. Zygos has no record of what a model is good at, so it cannot route by task.
   `ModelService.select_model` computes a route that `generate`/`stream` ignore.
4. Loading a different local model on a single GPU takes seconds and can evict the
   current one; nothing manages or shows this.
5. RFC-0009 designed text routing as config-only rules and left "what fits" open.

## Proposed Design

### 1. Hardware scan

A `HardwareProbe` (new, `zygos/hardware/`) reports, on start and on demand:
GPU name, VRAM total and free (via `nvidia-smi`, as `zygos doctor` already does),
system RAM total and available, CPU model and core count, and free disk space where
models are stored. Anything it cannot detect is `unknown` — never a guess. Other GPU
vendors and macOS unified memory are out of scope for the first build; they report
`unknown` and the fit check degrades to "can't tell" (§3). The scan appears in the
runtime manifest, `zygos doctor`, and the Models page.

### 2. Model profiles

One JSON file per model, at `.zygos/models/profiles/<provider>/<model>.json` (model
names are made filesystem-safe; the original name is stored inside). Profiles are
local, human-readable and hand-editable.

**Model families** (maintainer's point: a user is likely to have several models of one
family — e.g. qwen3.x in several sizes and versions plus `-instruct`, coder and OCR
variants). My calls: every variant has **its own profile and its own scores** — a
coder variant, a larger size or another quantization is tested separately, because
they behave differently and inherited scores would be guesses. Two names for the
same model (e.g. `qwen3:latest` and `qwen3:8b`, same digest) share one profile. The
picker **groups models by family**, showing size, quantization and specialty side by
side so variants can be told apart.

Every value is a record `{value, source, at}` where `source` is one of `ollama`,
`modelfile`, `measured`, `eval`, `user` or `name` (a hint read from the model's name,
lowest precedence), and `at` is a timestamp. Sections:

- **identity:** provider, model, family, parameter count, quantization, download
  size, maximum context length, content digest, and **specialty** (e.g. `coder`,
  `instruct`, `vision`/`ocr`) — from Ollama's `details` where given, otherwise a `name`
  hint from tags such as `-coder`, `-instruct`, `-vl`, `-ocr`.
- **capabilities:** tools, vision, thinking, embedding (from Ollama `/api/show`
  `capabilities`, the probe RFC-0012 already uses).
- **performance (measured in normal use, free):** writing speed (tokens and words per
  second), time to first token, load time, VRAM used when loaded (Ollama `/api/ps`
  `size_vram`). Rolling medians over recent turns.
- **quality (per task category):** `code`, `reasoning`, `chat` — each a score, sample
  count, suite version and date. `code` and `reasoning` are filled by **eval runs**;
  `chat` by the **user's own ratings** (§7). Never inferred from normal use.
- **user:** tags, notes, and overrides for any field above.

Precedence when reading a field: `user` > `eval` > `measured` > `modelfile` >
`ollama`. Zygos only ever writes the non-user sections and never rewrites the `user`
section. A profile is created when a model is first seen (installed list, download,
or first use) from Ollama's `/api/show`; cloud models (OpenAI, Anthropic) get a
profile with capabilities and performance only, and no fit check (§3); they may be
eval-tested, and are only ever suggested under the rules in §6.

### 3. Fit check

`fit(profile, hardware) -> Fit` with levels:

- **gpu** — the estimated footprint fits in free VRAM.
- **partial** — it doesn't fit in VRAM but fits in VRAM + available RAM; Ollama
  splits it across GPU and CPU, which works but is much slower.
- **no** — it doesn't fit even with RAM.
- **unknown** — size or hardware unknown; allowed, with a warning.

Estimated footprint = download size + a context allowance (KV cache for the
configured context length) + a fixed runtime overhead. "Free VRAM" counts what else
is resident: other loaded Ollama models (`/api/ps`) and Kokoro on CUDA (≈1.4 GB,
RFC-0005 §2a). The estimate is shown with its parts ("needs ≈9.8 GB: 8.1 GB model +
1.2 GB context + 0.5 GB overhead; 6.1 GB free") so it can be checked. Once a model has
been loaded, its **measured** VRAM replaces the estimate. The exact context-allowance
formula is a build-time decision, validated against measured `size_vram`.

### 4. The model picker (web app)

The Models page (today read-only, RFC-0011) becomes:

- **Installed models** (Ollama `/api/tags`, plus configured cloud routes), each with
  its fit badge, size, capabilities, and a profile summary (speed, any quality scores
  with source and date).
- **Set as default.** Saved in the local preferences store (a `model_choices` record next to RFC-0010's store
  holds `default_model {provider, model}`, §10), taking precedence over `providers.primary`
  in the config file, applied from the next turn — no restart. The config file is
  never rewritten. "Reset to config default" clears it. A model that doesn't fit can
  still be chosen after a confirmation that names the reason.
- **Download.** Enter a model name (an Ollama library tag such as `gemma4:12b`, or a
  Hugging Face GGUF reference `hf.co/<user>/<repo>:<quant>`, which Ollama pulls
  natively). The **fit check runs before the download** and the user confirms;
  then Ollama `/api/pull` streams progress (status, completed/total bytes), shown
  live and cancellable. Free disk space is checked first. On success a profile is
  created.
- **Test this model** runs the eval suites for it (§7) and fills its quality section.

- **Delete** a model (Ollama `DELETE /api/delete`), after a confirmation showing the
  disk space freed. Not allowed for the model currently loaded or answering, or for
  the saved default (reset or change the default first). Its profile is kept, marked
  not installed, so scores survive a re-download.

**Size before download (settled 2026-11-04, checked against the live services).**
- Ollama library models: the registry manifest
  (`registry.ollama.ai/v2/library/<model>/manifests/<tag>`) lists each layer's size —
  e.g. `qwen3:8b` model layer 5,225,374,496 bytes. Undocumented, but it is the protocol
  Ollama itself pulls with.
- Hugging Face GGUF: the Hub's file listing (`huggingface.co/api/models/<repo>/tree/main`)
  gives each file's size (e.g. `unsloth/Qwen3-8B-GGUF` IQ4_NL = 4,793,624,384 bytes);
  the requested quantization is matched to its file.
- Any lookup failure → size `unknown` → fit `unknown`, and the user confirms before
  downloading. A broken lookup never blocks a download.

**Search (settled 2026-11-04).** Ollama has no search API (ollama.com search is an
HTML page; the registry's tag list returns 404), so there is **no Ollama search**
unless Ollama publishes one — the picker links to ollama.com's library for browsing.
The first build offers **download by exact name**. A later phase adds **Hugging Face
search** (the Hub's model search with a `gguf` filter, sorted by downloads), each
result showing its fit.

### 5. Per-turn selection (load-bearing routing)

Taken from RFC-0009 §1–§2, unchanged in substance:

- The session's message thread is the context; handing it to another model is a
  provider swap, not a migration.
- `ModelService.generate`/`stream` gain an optional `route: RouteChoice | None`.
  `None` is exactly today's behaviour. With a route, the turn is authored by that
  route, and on hard failure falls back to the default route.
- The **default route** is the saved default (§4) if it is set, still installed and
  routable; otherwise `providers.primary`. The saved default is a layer **above** the
  router, not a new router entry: on hard failure of whichever route authored the turn,
  the router's normal order (`providers.primary`, then `providers.fallbacks`) applies,
  and the answer's `model` field names the model that actually answered. A saved
  default whose model has been deleted is ignored, with a notice on the Models page and
  a `zygos doctor` warning, until the user picks again.
- The default is **read per turn**, not snapshotted per session: a change applies to
  every session's next turn; a turn already running is unaffected.

At turn start the runtime classifies the request into a task category and records
it. The existing `classify_task` is a keyword heuristic returning `code`,
`complex_reasoning`, `simple` or `standard`; it maps to `code`, `reasoning`, `chat`
(simple and standard). A better classifier is a later change behind the same
function; misclassification only costs a wrong suggestion, never a wrong answer,
in the default mode.

A model's specialty never routes a turn by itself (my call): a `coder` tag is a
label, not a score. Routing uses only quality scores and capabilities, so a coder
variant gets code turns once its code score earns them. A vision or OCR variant
matters for turns with image input, which arrive with RFC-0009's vision work and are
routed by the `vision` capability; until then such models are picked by hand.

With several close variants, **only one model is suggested**: the highest score for
the category; if two are within the margin of each other, the faster one (measured
writing speed) (my call). The category of every turn is shown in Inspect, so
misclassification is visible; a better classifier is built only if those records show
the keyword rule is the problem (maintainer agreed).

### 6. Suggest, or switch automatically

**Suggest (the default).** The turn is answered by the default model. After
`turn.end`, if another model **fits** (`gpu`, or `partial` only if the user allows
it) and its profile's quality score for the turn's category beats the default's by
a margin (a named constant, initially 15 percentage points, with at least
`MIN_EVAL_SAMPLES` samples behind both scores), the answer gets an **"Ask <model>"**
action with the reason ("better at code: 7/7 vs 0/7"). Choosing it re-asks the same
question with that model as a new turn — the original answer stays, exactly like
RFC-0012's "Think it through". No score, no suggestion: Zygos never suggests on
guesswork. A model without quality data is never suggested.

**Auto-switch (opt-in setting, off by default).** When on, the same rule picks the
model *before* answering. The answer is labelled "answered by <model> (<category>)",
and a needed swap shows "loading <model>…". The setting can be limited to chosen
categories (e.g. code only). **Voice turns never auto-switch by default** — the swap
delay lands before the first spoken word — they get the suggestion instead; a
separate setting allows it.

A turn that is a re-ask, or that already uses a non-default model, never triggers a
further suggestion for the same question.

**Capability match.** A model is only a candidate if it has every capability the turn
needs: `tools` when tools are configured (RFC-0008), `thinking` when the turn thinks
(RFC-0012). A model's extra capabilities never count in its favour.

**Comparable scores only.** Two models' scores are compared only when they come from
the same suite version; otherwise there is no suggestion. No profile score comes from a
judge model (§7). `MIN_EVAL_SAMPLES = 10` per category.

**Re-asks** work exactly like RFC-0012's: a new turn on the same question; both
exchanges are stored in memory as today, and the original answer stays in the chat.

**Cloud models** (OpenAI, Anthropic, any non-local route) are **never switched to
automatically**, whatever the auto settings say. They are suggested only when the user
turns on `routing.include_cloud` (off by default; maintainer's call). Turning it on, and
every cloud suggestion, carries a notice that the conversation is sent to that provider
**and that not all of Zygos's functionality remains**: Zygos has much less visibility
into a cloud model than a local one — for example the model's thinking may be hidden or
summarised, and memory use, load time and fit don't apply — so Inspect shows less for
those turns. The exact list per provider is checked at build time and shown in the
notice; Inspect marks a cloud-answered turn as such. Testing a cloud model with the
eval suites costs API money and says so, with the number of requests, before starting.

### 7. Learning what a model is good at

- **Performance** is recorded from every turn (free): the turn loop already measures
  time to first token and writing speed (the sentence-streaming pacer).
- **Quality for `code` and `reasoning`** comes from **eval runs**, started by "Test
  this model" or `python -m zygos.eval <suite> --model <provider>:<model>`, scored
  **without a judge model**: `code` by running the model's code (below), `reasoning`
  by checked answers
  (`exact_match` / `normalized_match`). Only one model is loaded during a run. The
  existing reasoning suite's `llm_judge` items stay available to the research harness
  but don't count towards profile scores (my call). Each run writes the score, sample
  count, suite version and date to the profile. Runs can take many minutes on local
  hardware and say so before starting. **Chat comes first** (maintainer agreed): if a
  user turn arrives during a run, the run pauses after its current item, the turn
  runs (loading its model if needed), and the run resumes; the Models page shows the
  run as running or paused, with progress, and it can be cancelled.
- **A code item** (maintainer's call) is: (a) a **prompt** describing the code to
  write; (b) **our working, completed reference solution**; and (c) the tests that
  define "works". The model's code is scored on **functionality only**: it passes if
  it behaves like the reference under the tests (run by the harness's existing
  `code_exec` scorer, sandboxed). Style, naming, and comments missing or added never
  count against it. The reference solution must pass its own tests — the suite's own
  check that each item is correct — and inputs the tests use may also be run through
  the reference to produce the expected outputs.
- **Quality for `chat` is scored by the user** (maintainer's call — a judge model
  would have to run alongside the chat model, which local hardware won't do well),
  and rating is **never required** (maintainer's call):
  - **"How was this conversation?"** — occasionally, a small dismissible card asks
    for a rating **outside the conversation** (not as a chat message, never blocking
    input), like the rating prompts in hosted assistants. My calls: it appears only
    after a conversation has gone quiet (no turn for a while) or when the user leaves
    it, at most once per conversation and at most once a day, never during voice
    playback, and it can be switched off (`ratings.ask`, on by default). Ignoring or
    dismissing it records nothing.
  - **"Rate this model"** on the Models page, optional: runs the chat suite's prompts
    through the model and shows the answers to rate; when rating several models,
    answers are shown **without model names** and in mixed order (my call).
  - Ratings are **good / okay / poor**, scored 1 / 0.5 / 0 (my call). A conversation
    rating counts for a model only if that model answered every chat turn in it (my
    call — a mixed conversation can't be credited fairly). `MIN_EVAL_SAMPLES` applies:
    at least 10 ratings before a model can be suggested for chat. Conversation ratings
    are a weaker signal than a suite (they depend on what was asked), so the chat
    score shows its count and source.
- **Starter suites** for `code`, `reasoning` and `chat` are written by the builder
  and ship with Zygos, versioned. Their contents — how many items, and how easy or
  hard — are **agreed with the maintainer before Phase 4 is built**: a suite every
  model passes, or every model fails, can't tell models apart.
- **Weak signals from use** (e.g. a "Think it through" re-ask after a quick answer)
  are **recorded as counts only** and never feed scores in this RFC — a later RFC may
  use them once there is data to judge them.

### 8. Residency (loading and unloading local models)

Taken from RFC-0009 §6: before a local model authors a turn, `ensure_resident` loads
it, unloading another if the fit check says both don't fit (Ollama `keep_alive`).
Cloud models are a no-op. The load time is measured into the profile and shown as
"loading <model>…". Loads are **serialised** behind one residency lock, and a model
with a turn in flight is never evicted — the load waits for that turn to finish
(Ollama may otherwise unload a model mid-stream). When the user changes the default, the new model is loaded in the
background so the next turn doesn't wait. A background load superseded by another
change is cancelled.

### 9. Context fit

Taken from RFC-0009 §7: when a model with a smaller context window authors a turn,
the existing memory/retrieval and per-model token limits (ADR-0006) decide what is
included. Switching the authoring model only changes which limit applies.

### 10. Wire protocol (additive, RFC-0007 §2)

- REST: `GET /models` (installed + cloud, with profile summary and fit), `GET /hardware`,
  `PUT /models/default {provider, model}` / `DELETE /models/default`,
  `POST /models/pull {name}` (returns a pull id), `DELETE /models/pull/{id}` (cancel),
  `DELETE /models/{provider}/{model}` (delete the model; refused for the loaded,
  answering or saved-default model), `GET /models/size?name=` (pre-download size),
  `DELETE /models/eval/{run_id}` (cancel a test run),
  `POST /models/{provider}/{model}/eval {suite}` (code/reasoning runs; for `chat` it
  returns the answers to rate), `POST /models/ratings {items: [{answer_id, rating}]}`,
  `POST /sessions/{id}/rating {rating}` (the conversation prompt),
  `PATCH /models/{provider}/{model}/profile` (user section only).
- WS: `control:models.pull {id, status, completed, total}` progress frames;
  `chat:turn.end` gains optional `model {provider, model}`, `category`, and
  `suggestion {provider, model, reason} | null`; `chat:user_message` gains optional
  `route {provider, model}` and `reask_of` (the suggested re-ask).
- Settings: `routing.mode: suggest | auto` (default `suggest`),
  `routing.auto_categories`, `routing.auto_in_voice: false`,
  `routing.allow_partial_fit: false`, `routing.include_cloud: false`,
  `ratings.ask: true`. Stored with `default_model` in a separate
  `model_choices` record in the same local preferences directory as RFC-0010's store
  (not inside the personalization schema), per install (Zygos is single-user), and
  edited through `PUT /models/default` and `PUT /models/routing` — not through
  `/preferences`. Editable from the Models page.

### 11. Inspectability

New trace events: `model.selected {turn_id, category, route, mode, reason}`,
`model.suggested {turn_id, category, suggested, reason}`, `model.loaded
{provider, model, load_ms, evicted}`, `model.fit {provider, model, level, needs,
free}`. Inspect shows per turn which model answered and why, and the Models page
shows each profile field with its source and date.

## Alternatives Considered

- **Config-only routing rules (RFC-0009 Path C).** Kept as a fallback (`user`
  overrides can pin a category to a model), but rejected as the main path: it asks the
  user to know in advance what each model is good at, which is what profiles record.
- **Auto-switch by default.** Rejected: a wrong guess silently gives a worse answer,
  and a swap adds seconds — worst in voice. Suggesting after the answer costs nothing
  when wrong.
- **Ask before answering ("Use gemma4 for this?").** Rejected: adds a confirmation
  step before every routed answer.
- **One shared profiles database.** Rejected for per-model JSON: inspectable,
  hand-editable, easy to delete or share.
- **Scoring quality from everyday use.** Deferred: there is no ground truth in a
  conversation; eval runs give comparable numbers.
- **Writing the chosen model back into the config file.** Rejected: the config file is
  the user's; runtime choices live in the preferences store.

## Migration Plan

Additive and default-preserving; built in phases, each its own cycle:

1. **Hardware scan + profiles + fit check**, read-only on the Models page and in
   doctor/manifest.
2. **Picker:** saved default without restart; load-bearing `route`; residency.
3. **Download** by exact name with size lookup, fit check and progress; **delete**.
   (Hugging Face search follows as its own later step.)
4. **Category eval suites, "Test this model" and chat rating** filling quality —
   suite contents agreed with the maintainer first.
5. **Suggest, then auto-switch.**

With no saved default, no profiles with quality data, and `routing.mode` at its
default, behaviour is exactly today's: one model from config, no suggestions.

## Risks

- **Fit estimates wrong.** Mitigated by showing the estimate's parts, replacing it
  with measured VRAM after first load, `unknown` instead of guessing, and allowing
  an override after confirmation.
- **Bad suggestions.** Mitigated by requiring eval data with a minimum sample count
  and a margin; no data → no suggestion; every suggestion shows its reason.
- **Swap thrash on one GPU** (auto mode alternating models). Mitigated by auto being
  opt-in and per category, voice excluded by default, and load time shown in Inspect.
- **Eval suites too small to mean much.** Mitigated by showing sample counts beside
  every score; suites are versioned so old scores are recognisable.
- **Chat rating is optional**, so chat scores fill slowly or stay empty. Accepted: no
  chat score simply means no chat suggestion; code and reasoning work without it.
- **Cloud suggestions send data off the machine.** Mitigated by never auto-switching
  to cloud, an off-by-default setting, and a notice on every cloud suggestion.
- **Downloads are large** (several GB). Mitigated by the fit and disk checks before
  starting, live progress, and cancel.
- **Undocumented size lookups** (Ollama registry manifest). Mitigated by treating any
  failure as size `unknown`; a download is never blocked by it.

## Acceptance Criteria

1. `GET /hardware`, the manifest and `zygos doctor` report GPU, VRAM, RAM, CPU and
   disk, with `unknown` for anything undetected.
2. A profile is created for each installed model from `/api/show`; values carry
   source and date; a `user` edit overrides every other source and survives Zygos's
   own updates.
3. The fit check returns gpu/partial/no/unknown with the estimate's parts; after a
   model is loaded, its measured VRAM is used.
4. Setting a default in the web app takes effect on the next turn without a restart,
   survives a restart, and doesn't change the config file; reset restores the config
   model.
5. Downloading by exact name looks up the size, runs the fit and disk check first,
   streams progress, can be cancelled, and creates a profile; a failed size lookup
   gives fit `unknown` and still allows the download after confirmation. Deleting a
   model frees its disk space, is refused for the loaded, answering or saved-default
   model, and keeps its profile.
6. `generate`/`stream` with `route=None` behave exactly as today; with a route, the
   turn is authored by it and falls back to the default on hard failure.
7. With quality data meeting the margin and sample rule, a turn whose category another
   fitting model is better at gets an "Ask <model>" action with its reason; choosing
   it re-asks with that model and keeps the original answer. Without data, no action.
8. With `routing.mode: auto`, the model is chosen before answering, the answer is
   labelled, a swap shows "loading <model>…", and voice turns don't switch unless
   `routing.auto_in_voice` is on.
9. "Test this model" / `python -m zygos.eval … --model` writes `code` and `reasoning`
   scores with sample counts and dates to the profile, using no judge model; a code
   item passes on behaviour alone (comments and style never count) and every
   reference solution passes its own tests. Chat ratings, from the occasional
   conversation card or "Rate this model", become the `chat` score; rating is never
   required, dismissing the card records nothing, and `ratings.ask: false` stops it.
10. Every selection, suggestion, load and fit decision appears as a trace event and in
    Inspect.
11. With defaults, a fresh install behaves exactly as before this RFC.
12. A cloud model is never chosen automatically; it is suggested only with
    `routing.include_cloud` on, and every cloud suggestion shows the data and
    reduced-visibility notice.
13. Each variant in a model family has its own profile and scores; two names for the
    same digest share one; the picker groups by family; at most one model is
    suggested per turn.
14. A chat turn sent during a test run is answered without waiting for the run to
    finish; the run pauses and resumes.

## Architectural Impact

- **Coupling:** adds a `hardware` module and a `models` (profiles, fit, routing)
  module consumed by `ModelService` and the API; providers gain read-only Ollama calls
  (`/api/tags`, `/api/ps`, `/api/pull`) behind the provider seam, not called from the
  UI directly.
- **Hidden state:** none new that isn't visible — profiles are files the user can
  read and edit; the saved default and routing settings are in the preferences store
  and shown on the Models page; every routing decision is traced.
- **Service boundaries:** routing goes through `ModelService` (RFC-0001 §2) as RFC-0009
  intended; no caller talks to a provider around it.
- **Constitution:** no conflict found. Privacy (the user's data stays theirs) is kept
  by never moving a conversation to the cloud without the user choosing it each time. In keeping with the project's "user choice
  over forced models" practice: routing suggests by default and the user can always
  pick; inspectable by construction.
- **Testable independently:** the probe, profiles, fit check and routing rule are pure
  or injectable (fake `nvidia-smi` output, fake Ollama responses).
- **New service?** No new long-running service; modules inside the runtime.
- **Removable:** with no saved default and `routing.mode` unset, the runtime behaves as
  today; the modules can be removed without touching the turn loop beyond the optional
  `route`.
