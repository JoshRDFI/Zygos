# RFC-0014: Inference Backends — Zygos-Run llama.cpp, vLLM Endpoints, and Backend Setup

- **Status:** Accepted (2026-11-04)
- **Author:** Zygos maintainers
- **Created:** 2026-11-04
- **Governs:** which local inference backends Zygos works with and what it does
  for each: **llama.cpp**, which the user installs and **Zygos starts and stops**
  with launch settings the user types (a default and per-model); **vLLM**, which the
  user runs and Zygos only points at; and **Ollama**, as today. How backends are set
  up (a step in `zygos personalize` and the Models page), how llama.cpp models are
  found (one folder of GGUF files), how launch settings feed the fit check, how the
  GPU is handed between backends, and how measurements are tied to the settings they
  were taken with.
- **Depends on:**
  [RFC-0013](RFC-0013-Model-Picker-Profiles-and-Task-Routing.md) (profiles, fit
  check, picker, per-turn routing and residency — this RFC extends each to the new
  backends),
  [RFC-0001](RFC-0001-Service-Architecture.md) (the `Provider` contract a llama.cpp
  provider implements),
  [RFC-0010](RFC-0010-User-Personalization-and-Assistant-Identity.md) (the
  `zygos personalize` flow the setup step joins),
  [RFC-0012](RFC-0012-Native-Thinking-Controls.md) (thinking controls, which need a
  llama.cpp path), and
  [RFC-0003](RFC-0003-Capability-Registry-Runtime-Manifest-and-Inspection.md)
  (`zygos doctor`, the manifest).
- **Amends (additively):** RFC-0013 §2 (a measurement or score may carry the
  launch settings it was taken with), §3 (the fit check reads llama.cpp launch
  settings), §8 (residency covers starting/stopping `llama-server` and the GPU
  hand-off between Ollama and llama.cpp); RFC-0010 §2 (onboarding gains an optional
  backend step after the identity questions; skipping it changes nothing).
- **Does not govern:** installing llama.cpp, vLLM or Ollama (the user does; Zygos
  points to their install pages); running vLLM (the user does); remote compute
  (Archon `b73b0912`); running two models at once (explicitly not wanted).

## Summary

Zygos is a platform for watching how models behave. llama.cpp exposes the knobs
Ollama hides — how many layers go on the GPU, keeping mixture-of-experts expert
weights on the CPU, quantizing the context cache, batch sizes — and with them runs
models Ollama won't fit on a small GPU. This RFC lets a user who already has
llama.cpp tell Zygos where `llama-server` is and where their GGUF files are; Zygos
then lists those models with profiles and fit, and **starts `llama-server` itself**
with whatever launch settings the user typed for that model (or the default), one
model at a time. vLLM stays something the user runs; Zygos lists the model it
serves. Ollama and llama.cpp can both be set up; Zygos hands the GPU from one to
the other when both won't fit. Speed and scores are recorded against the exact
settings they were measured with, so comparing settings — one after the other —
gives honest numbers.

## Motivation

- Observability: changing a model's launch settings and seeing the effect is the
  kind of experiment Zygos exists for; Ollama doesn't expose most of these settings.
- Reach: settings such as partial GPU offload (`-ngl`), CPU-resident MoE experts
  (`--n-cpu-moe`) and quantized KV cache (`-ctk`/`-ctv`) let larger models run on
  a 16 GB card.
- vLLM is already a provider (`zygos/providers/vllm.py`) but the model picker
  (RFC-0013) only knows Ollama; it should at least list what vLLM serves.

## Problem Statement

1. Zygos can't run llama.cpp models at all.
2. Launch settings that change memory use and speed aren't visible to the fit
   check or to Inspect.
3. With two local backends on one GPU, nothing decides who holds the GPU.
4. A score measured with one set of settings would silently be reused for another.
5. The Models page shows nothing for a vLLM route.

## Proposed Design

### 1. The three backends

| | Ollama | llama.cpp | vLLM |
|---|---|---|---|
| Installed by | user | user | user |
| Server run by | Ollama | **Zygos** (`llama-server`) | user |
| Zygos needs | address (default `http://localhost:11434`) | path to `llama-server`, GGUF folder | address |
| Lists models | `/api/tags` | scan of the GGUF folder | `/v1/models` |
| Launch settings | — | default text + per-model text | — (user's command) |
| Fit check | yes (RFC-0013) | yes, using the launch settings | no — vLLM reserves its GPU share at start |
| Load / unload | `keep_alive` (RFC-0013 §8) | start / stop the process | none (always on) |
| Download | RFC-0013 phase 3 | later phase: Hugging Face GGUF into the folder | no |

A llama.cpp provider is added to the local-provider set the Models page uses
(`LOCAL_PROVIDERS`, RFC-0013 phase 1), so it is never labelled cloud.

### 2. Setup

**In `zygos personalize`** (after the identity questions, skippable, nothing saved
until confirmed — RFC-0010's review-before-save rule):

- **Ollama:** Zygos checks the configured or default address and says whether it
  answered. Nothing to enter unless the address differs.
- **llama.cpp:** "Do you have llama.cpp installed?" If no: Zygos says where to get
  it (the llama.cpp releases and build instructions) and that they can come back to
  this step any time (`zygos personalize backends`). If yes: the path to
  `llama-server` (Zygos runs `<path> --version` and shows the version, or the
  error), the folder holding GGUF files (Zygos counts what it finds), and an
  optional **default launch settings** text.
- **vLLM:** "Do you run a vLLM server?" If yes: its address; Zygos calls
  `/v1/models` and shows the served model, or the error. **One vLLM server** in this
  RFC (maintainer's call: several servers — e.g. one per GPU — is a later
  expansion). So that the expansion needs no migration, the `backends` record stores
  vLLM as a list of `{name, base_url}` entries holding one entry named `vllm` (my
  call); the provider name, profile paths (`profiles/vllm/…`) and route key stay
  `vllm`.

**On the Models page:** the same settings, editable, plus each llama.cpp model's
own launch-settings box (§4).

**When changes apply (my call):** launch settings, the GGUF folder and the
`llama-server` path apply without restarting Zygos (the next start uses them; a
running server is restarted when its own settings change, after the current turn).
A changed Ollama or vLLM **address** applies after restarting Zygos — the providers
are built at startup — and the Models page and doctor say "restart Zygos to apply"
until then.

**Storage (my call):** a `backends` record in the local preferences directory,
beside RFC-0013's `model_choices` — not the config file, which stays the user's and
is never rewritten. Values in the record take precedence over the config file's
`providers.credentials.<name>.base_url`; `zygos doctor` shows which one is in effect.
New CLI: `zygos personalize backends` (just this step), `zygos personalize
backends show`.

### 3. llama.cpp models: the GGUF folder

- Zygos scans the folder and its subfolders for `.gguf` files on start, on the
  Models page's refresh, and after a download.
- **Grouping (my call):** split files (`<name>-00001-of-0000N.gguf`) are one model;
  a file whose name contains `mmproj` in the same directory as one model is that
  model's vision projector and is passed with `--mmproj`. Ambiguous projector
  matches (several models, several projectors in one directory) are listed for the
  user to pair on the Models page.
- A model's name is its path relative to the folder, without `.gguf`
  (e.g. `Qwen3-8B-GGUF/Qwen3-8B-IQ4_NL`).
- **Profile:** created from the GGUF file's own header — architecture, parameter
  count, layer count, KV-head geometry, trained context length, and per-tensor
  sizes — recorded under RFC-0013's `modelfile` source (it is the model file).
  Download size = total file size. The provider name is `llamacpp`. Reading the
  header needs no server and loads no weights.

### 4. Launch settings

- **Two boxes:** a **default** (backend-wide) and an **optional per-model** box. A
  model's own box replaces the default entirely for that model (maintainer's call:
  per model, with a default for models without their own). Both are plain text, as
  typed after `llama-server`.
- **Zygos sets** `-m/--model`, `--host`, `--port`, `-a/--alias` and, when a
  projector is paired, `--mmproj`. If the text contains one of these, saving is
  refused with a message naming it (my call). `--host` is always `127.0.0.1`, so the
  server is never reachable from the network; the port is a free one Zygos picks.
- **Parsing (my call):** the text is split like a shell would split it (quotes
  respected) into separate arguments and passed to the process directly — **never
  through a shell**. Zygos doesn't judge other flags; `llama-server` does, and if it
  refuses them its own error output is shown (§5).
- **Read for the fit check:** `-c/--ctx-size`, `-ngl/--n-gpu-layers` (number or
  `all`), `-ctk/--cache-type-k`, `-ctv/--cache-type-v`, `--n-cpu-moe`,
  `-np/--parallel`, `--no-kv-offload`. Each is shown in the estimate's parts.
- **A split the user chose (my call).** When the settings put part of the model on
  the CPU (`-ngl` below the layer count, `--n-cpu-moe`, `--no-kv-offload`), the
  estimate has a **GPU part** and a **CPU part**, computed from the GGUF's per-tensor
  sizes. The fit is `gpu` when everything is on the GPU and fits; `partial` when the
  user's split puts some on the CPU and **both parts fit** (VRAM and RAM) — shown as
  "split by your settings", not as a warning; `no` when either part doesn't fit;
  `unknown` as in RFC-0013. The GPU hand-off (§6) compares only the GPU part with
  free VRAM. `Fit` gains optional `gpu_bytes` / `cpu_bytes` and a `split_by:
  "settings" | null` field; existing fields keep their meaning.
- **Flags Zygos needs for features (my call):** tool calling and thinking controls
  rely on `llama-server`'s Jinja chat templates; Zygos adds `--jinja` unless the
  text turns it off, and says on the Models page when tools or thinking are
  unavailable because of a setting. Exact flag names are checked against the
  installed version at build time (llama.cpp's flags change between releases;
  `zygos doctor` shows the version).

### 5. Running `llama-server`

- **One owner (my call).** The `zygos serve` process owns `llama-server`. Its
  supervisor writes a state file (`.zygos/run/llamacpp.json`: PID, port, model,
  settings id, started at, last output tail) and holds a lock file while it runs a
  server. Other Zygos processes never start a second one:
  - `zygos doctor` and `zygos personalize backends show` read the state file (and
    check the PID is alive) to report the running model, port and last output.
  - `python -m zygos.eval … --model llamacpp:<model>` goes through the running
    server's `POST /models/llamacpp/<model>/eval` (RFC-0013 §10) when `zygos serve`
    is up; when it isn't, the eval process takes the lock itself, starts and stops
    its own `llama-server`, and `zygos serve` refuses to start one while that lock is
    held (and says why).
  - Orphan cleanup (§Risks) only stops a recorded server whose lock is not held by
    a live process.
- **Routes from config (my call).** `llamacpp:<model>` may be `providers.primary` or
  a fallback in the config file. The provider asks the supervisor to make sure that
  model is running before each request (`ensure_running(model)`), so a route used
  only as a fallback starts the server when it is needed; the provider's base URL
  is the supervisor's current port, read per request, never fixed at startup.
- **One at a time** (maintainer's call: no side-by-side). Switching model or
  settings stops the running server and starts a new one; this is RFC-0013 §8's
  "load", serialised behind the same residency lock, and never while a turn is
  using the running server.
- **When:** started when a llama.cpp model is needed — the next turn's model, or
  set as default (loaded in the background, RFC-0013 §8). Stopped when switching,
  when the GPU is handed to Ollama (§6), and when Zygos exits. Zygos only ever stops
  processes it started.
- **Ready:** Zygos polls `GET /health` until it answers 200 (model loaded), with a
  load timeout (a named constant; default 300 s, matching the provider timeout).
  Load time is measured into the profile.
- **Failure:** if the process exits or the timeout passes, the last lines of its
  output (a named constant, e.g. 40 lines) are kept and shown on the Models page,
  in `zygos doctor` and in a `backend.failed` trace event; the turn falls back as
  RFC-0013 §5 says. A crash mid-turn is a provider error for that turn; the next
  turn that needs it starts it again, once, before reporting failure.
- **Measured VRAM (my call on the fallback):** after start, Zygos reads the
  process's GPU memory from `nvidia-smi --query-compute-apps=pid,used_memory`. Where
  that isn't reported (common on WSL2, the maintainer's setup), it uses the drop in
  free VRAM from just before the start to just after `/health` answers, noted as
  "measured (free-VRAM change)". If neither works, the estimate stays and says so.
  The measured value is recorded as `measured` (replacing the estimate, RFC-0013
  §3).

### 6. One GPU, two backends

Ollama and llama.cpp can both be set up (maintainer's call). RFC-0013 §8's rule
applies across them: before one backend loads a model, if the fit check says it
won't fit beside what the other holds, Zygos frees the other first — stopping
`llama-server`, or unloading Ollama models (`keep_alive: 0`). If both fit, both
stay. vLLM's memory is never reclaimable (Zygos doesn't run it); it is simply
counted as used.

### 7. The llama.cpp provider

A `llamacpp` provider speaking `llama-server`'s OpenAI-compatible chat API (like
the existing `vllm` provider), with streaming, tool calls and usage. Its base URL
is the running server's port. Thinking (RFC-0012): when the model's chat template
supports a thinking switch, the request passes it per turn; the thinking text comes
back in the response's reasoning field and is shown as for Ollama. Support
detection reads the model's chat template from the server (`/props`) — unsupported
is said so, as RFC-0012 requires. Native audio, vision input and embeddings via
llama.cpp are out of scope here.

### 8. Measurements tied to settings

- Every llama.cpp performance measurement and eval score records a **settings id**:
  a short hash of the model files plus the effective launch arguments (sorted
  where order doesn't matter is a build-time choice; exact text is fine).
- The profile keeps a small table `settings id → launch text, first used`. The
  Models page shows the current settings' numbers, with earlier settings' numbers
  listed beneath ("with `-ngl 20 -ctk q4_0`: 18 tokens/s, code 5/7").
- Suggestions and auto-switching (RFC-0013 §6) use only the numbers for the
  model's **current** settings. Changing settings starts fresh numbers; nothing is
  deleted.
- Ollama and vLLM measurements carry no settings id in this RFC.

### 9. vLLM in the picker

The Models page lists the model the configured vLLM address serves (from
`/v1/models`: id and maximum context length), with a profile (provider `vllm`,
capabilities unknown unless the user sets them) and "fit not checked: vLLM reserves
its GPU share at start". It can be chosen as the default like any other model.
vLLM is never started, stopped or downloaded to by Zygos.

### 10. Wire protocol and inspectability (additive)

- REST: `GET /backends` (each backend's settings, status, version, running model,
  port, last error output), `PUT /backends` (setup), `PUT
  /models/llamacpp/{model}/launch {text | null}` (per-model box; null = use
  default), `POST /backends/llamacpp/restart`.
- Trace events: `backend.started {provider, model, args, port, load_ms,
  settings_id}`, `backend.stopped {provider, model, reason}`, `backend.failed
  {provider, model, exit_code, output_tail}`. Inspect shows, per turn, the backend
  and — for llama.cpp — the launch settings the answer was produced with.
- `zygos doctor`: llama.cpp path exists, is executable, and its version; GGUF folder
  exists and how many models it holds; vLLM address answers and what it serves;
  which address (preferences or config) is in effect for each.

## Alternatives Considered

- **Zygos installs llama.cpp.** Rejected (maintainer): users who want llama.cpp
  have it; builds differ by GPU and OS.
- **Connect to a user-run `llama-server`.** Rejected (maintainer): Zygos must start
  it to apply per-model settings and to switch models.
- **A settings form with fields per option.** Rejected (maintainer): a text box
  keeps every llama.cpp option available as the user knows it; Zygos reads only the
  options it needs.
- **Running two models side by side for comparison.** Rejected (maintainer):
  compare sequentially; settings-tagged numbers (§8) keep the comparison honest.
- **Zygos runs vLLM too.** Rejected (maintainer): vLLM setups vary too much;
  Zygos points at it.
- **One backend per install.** Rejected (maintainer): both Ollama and llama.cpp
  can be set up, with a GPU hand-off.
- **Several vLLM servers now.** Deferred (maintainer): useful with several GPUs,
  but not needed yet; the record's list shape leaves room for it.

## Migration Plan

Additive; with nothing set up, behaviour is exactly today's. Phases, each its own
cycle, after RFC-0013 phase 1 (built). Phases 1–2 can be built now; phases 3–5 wait
for RFC-0013 phase 2 (saved default, load-bearing `route`, residency lock), and the
first plan written from this RFC covers phases 1–2 only:

1. **Setup + doctor:** the `backends` record, `zygos personalize backends`, the
   onboarding step, `GET/PUT /backends`, doctor checks.
2. **GGUF catalog:** folder scan, grouping, profiles from GGUF headers, fit check
   reading launch settings; listed on the Models page (read-only); vLLM listing.
3. **Running llama.cpp:** the provider, process lifecycle, launch boxes, measured
   VRAM, trace events, GPU hand-off with Ollama.
4. **Settings-tagged measurements** and the Models page history.
5. **Hugging Face GGUF download** into the folder (with RFC-0013 phase 3's
   size/fit checks).

## Risks

- **llama.cpp flags change between releases.** Mitigated by not validating flags
  ourselves, showing `llama-server`'s own errors, and showing its version.
- **A setting crashes or hangs the server.** Mitigated by the load timeout, output
  tail, fallback route, and a single automatic restart.
- **Fit estimates for partial offload / MoE are rough.** Mitigated by showing each
  part and replacing them with measured VRAM after start.
- **Orphaned processes** if Zygos is killed hard. Mitigated by recording the PID
  and, on start, stopping a recorded `llama-server` that is still running from a
  previous Zygos run (only if its command line matches what Zygos launched).
- **GPU hand-off thrash** when alternating backends. Mitigated by only freeing when
  the fit check says both won't fit, and showing load times.

## Acceptance Criteria

1. With no backend setup, behaviour is exactly as before.
2. `zygos personalize backends` asks about Ollama, llama.cpp and vLLM; a missing
   llama.cpp gets install guidance and nothing saved; a given path is checked with
   `--version`; nothing is saved until confirmed.
3. Every `.gguf` model in the folder is listed with a profile from its header, with
   split files and a paired projector grouped as one model.
4. The fit check for a llama.cpp model reflects `-c`, `-ngl`, `-ctk/-ctv`,
   `--n-cpu-moe`, `-np` and `--no-kv-offload` from its effective settings, and shows
   each part.
5. Text containing a Zygos-set flag is refused with the flag named; text is never
   run through a shell; the server binds only to 127.0.0.1.
6. Choosing a llama.cpp model starts `llama-server` with the model's own settings,
   or the default; a turn is answered by it; switching stops it first; Zygos exit
   stops it.
7. A failing start shows the server's output tail on the Models page and in doctor,
   and the turn falls back.
8. With Ollama holding the GPU, starting a llama.cpp model that doesn't fit beside it
   unloads the Ollama model first, and vice versa; when both fit, nothing is freed.
9. Measurements and scores for a llama.cpp model are recorded against its settings
   id; changing settings shows fresh numbers with the old ones listed; suggestions
   use only current-settings numbers.
10. The configured vLLM address's served model is listed and can be the default.
11. `backend.started/stopped/failed` appear as trace events; Inspect shows a turn's
    launch settings.

## Architectural Impact

- **Coupling:** a `llamacpp` provider behind the provider seam (RFC-0001), a
  process supervisor inside the runtime (not the API layer), a GGUF header reader,
  and catalog sources for llama.cpp and vLLM alongside Ollama's.
- **Hidden state:** none that isn't visible — settings in the preferences record and
  on the Models page; the running process, port and output tail in `GET /backends`
  and doctor; every start/stop as a trace event.
- **Service boundaries:** the supervisor is the only code that starts processes;
  turns reach `llama-server` only through the provider.
- **Security:** user-typed arguments are never passed to a shell; the server binds
  to loopback only; Zygos stops only processes it started.
- **Constitution:** in keeping with user choice over forced models (backends are
  options beside Ollama, never required) and privacy (everything stays local).
- **Testable independently:** argument parsing, grouping, header reading and the fit
  arithmetic are pure; the supervisor takes an injectable process launcher; the
  provider is tested against a fake OpenAI-compatible server.
- **Removable:** with no llama.cpp setup, no code path changes.
