# RFC-0005: Voice Interaction — Local Speech-to-Text and Text-to-Speech

- **Status:** Draft
- **Author:** Zygos maintainers
- **Created:** 2026-07-09
- **Governs:** the concrete voice **engines** behind the `speech_to_text` and
  `text_to_speech` capabilities, the sidecar process model that runs them, the
  runtime↔sidecar IPC contract, the browser↔runtime audio channels and control
  frames, browser-side turn-taking (VAD, endpointing, barge-in), and first-run
  provisioning of the voice binaries and models
- **Depends on:**
  [RFC-0001](RFC-0001-Service-Architecture.md) (the `VoiceService` interface §2,
  the multiplexed WebSocket and channel-tagged binary frames §7, PluginService
  and the composition root),
  [RFC-0002](RFC-0002-Runtime-Event-Bus-and-ExecutionContext.md) (event bus and
  `ExecutionContext` for cancellation of in-flight synthesis), and
  [RFC-0003](RFC-0003-Capability-Registry-Runtime-Manifest-and-Inspection.md)
  (the `SPEECH_TO_TEXT` / `TEXT_TO_SPEECH` capabilities, plugin advertisement,
  the runtime manifest, and `zygos doctor`). RFC-0003 explicitly deferred the
  voice **engines** to this RFC.
- **Implementation status:** tracked in [ROADMAP.md](../../ROADMAP.md); the
  browser↔runtime audio channels and control frames are **specified here and
  built in Milestone 8** (FastAPI adapter + WebSocket protocol); the engines and
  sidecars land after M8. Voice interaction is a **2.0-complete gate**.

## Summary

Define local-first **voice interaction** for Zygos: streaming speech-to-text and
text-to-speech that run as **separate CPU sidecar processes**, entirely outside
the LLM's GPU model management, so the language model keeps the GPU to itself.
Each direction is an independent plugin advertising an RFC-0003 capability
(`speech_to_text`, `text_to_speech`) behind RFC-0001's `VoiceService`, so a
deployment can mix engines per direction — including **voice in, text out**. The
default engines are **whisper.cpp** (`base.en`) for transcription and **Kokoro**
(ONNX, CPU) for a natural — not robotic — synthesized voice, with **Piper** as a
hardware-gated fallback floor. Turn-taking (voice-activity detection, endpointing,
barge-in) runs **in the browser** so only speech crosses the wire and barge-in is
a local reflex. Binaries and models are **fetched on first run** from official
upstream sources against pinned checksums, keeping Zygos a single artifact that
redistributes no third-party binaries.

## Motivation

Voice interaction — both input (STT) and output (TTS) — is a stated requirement
for Zygos 2.0 and must land before the build is called complete. It shapes the
WebSocket layer (binary audio streaming, barge-in), the plugin/capability model
(voice engines as swappable adapters), the inspection surface (health of a native
process the user cannot see), and the installer (native binaries and models per
platform). RFC-0001 defined `VoiceService` "now so the architecture is
voice-shaped from the start" and RFC-0003 split `speech` into `speech_to_text`
and `text_to_speech` "so a deployment can mix engines per direction," each
deferring the concrete engines to this RFC. This is that RFC.

The design is driven by a single confirmed constraint: **GPU VRAM contention.**
Sharing one GPU between the LLM (via Ollama) and voice models causes eviction and
thrash — Ollama's multi-second cold reload makes the assistant unusable whenever
a voice model touches the GPU. The same failure occurs on the maintainer's
RTX 5080 (Windows/WSL) and on Apple Silicon. The resolution is architectural, not
a tuning knob: **voice inference runs CPU-only, in its own processes, outside the
LLM's model manager.** GPU acceleration becomes an optional, hardware-gated
enhancement — never a requirement.

## Problem Statement

1. **The engines do not exist.** RFC-0001 and RFC-0003 defined the *interfaces*
   (`VoiceService`, the two capabilities) and deferred every concrete engine
   decision. Nothing today can transcribe or synthesize.
2. **Naïve GPU voice breaks the assistant.** Any design that lets a voice model
   share the GPU with the LLM reintroduces the confirmed VRAM-contention failure.
   The process and device model must make GPU contention *structurally*
   impossible in the default configuration.
3. **Native inference must not destabilize the runtime.** whisper.cpp, ONNX
   runtime, and Piper are native code. A segfault or a multi-second model load
   must not crash or stall the async runtime event loop.
4. **"Conversational" is a hard requirement, and it fights "don't stream
   silence."** The interface must feel like a natural conversation — no clicking
   per turn — yet the voice channel must not push silence across the network,
   which matters acutely for the droplet deployment.
5. **Natural voice, no cloning pipeline, CPU-only is a three-way tension.**
   Cloning-capable engines are heavy and want a GPU (reintroducing contention);
   the fast CPU engine (Piper) is more robotic than desired. A path is needed
   that is natural on CPU today and reaches "the voice the user wants" without a
   GPU cloning pipeline.
6. **Provisioning must not redistribute third-party binaries or ship per-platform
   builds.** Zygos should remain a single artifact, require no compiler on the
   user's machine, and not take on the licensing and upkeep burden of shipping
   someone else's binaries.

## Proposed Design

### 1. Capability and plugin mapping

Voice engines are ordinary RFC-0003 plugins. Two independent capabilities, two
independent plugins, one runtime-side facade:

| Capability (RFC-0003) | Plugin | Engine (default) | Sidecar |
|---|---|---|---|
| `SPEECH_TO_TEXT` | STT plugin | whisper.cpp `base.en` | STT sidecar |
| `TEXT_TO_SPEECH` | TTS plugin | Kokoro (ONNX, CPU) | TTS sidecar |

`VoiceService` (RFC-0001 §2) is the **runtime-side thin client facade** over
whichever plugins are active, exposing `transcribe_stream(audio) -> text events`
and `synthesize_stream(text) -> audio`. The two directions are **fully
independent**: "voice in, text out" is simply the `speech_to_text` plugin present
and the `text_to_speech` plugin absent. When a capability has no registered
plugin, `VoiceService` reports it unavailable and the UI hides that direction.

### 2. Process model — per-engine CPU sidecars

Each voice plugin **owns and supervises one sidecar process** that hosts its
engine. Sidecars are small Python workers (whisper.cpp via bindings or its bundled
server; Kokoro via `kokoro-onnx`/ONNX runtime; Piper via its binary). Every
sidecar pins **`device=cpu`** by default.

The process boundary does three concrete jobs — note that CPU-only inference is
already off the GPU, so isolation from Ollama is *not* the boundary's job here:

- **Keep CPU-bound inference off the runtime event loop.** Transcription and
  synthesis run in another process; the runtime stays responsive.
- **Crash-isolate native code.** A native crash restarts *that* sidecar; the
  runtime survives and health reflects the blip.
- **Own device selection independently.** A sidecar can later be flipped to GPU
  as a hardware-gated enhancement without the runtime knowing or caring.

Supervision (spawn, health, restart-with-backoff, shutdown) lives in the plugin,
reusing the PluginService lifecycle from RFC-0001. Sidecar liveness and last-error
are snapshotable state per RFC-0002, surfaced through RFC-0003 health.

### 3. Runtime↔sidecar IPC contract

- **Transport:** a Unix domain socket on Linux/macOS, loopback TCP on
  Windows/WSL, behind one transport interface chosen at sidecar spawn.
- **Framing:** length-prefixed frames. A frame is either a **JSON control
  message** (`start`, `partial`, `final`, `synthesize`, `chunk`, `end`, `cancel`,
  `health`) or a **raw PCM payload**.
- **Audio format on this hop:** 16 kHz mono PCM `s16le` — whisper.cpp's native
  input rate. The TTS sidecar synthesizes at Kokoro's 24 kHz and **resamples to
  16 kHz** before returning, so both hops carry one canonical format.
- **Backpressure:** bounded queues in both directions; a slow consumer applies
  backpressure rather than growing unbounded buffers. `cancel` drops queued
  audio immediately (barge-in path).

### 4. Browser↔runtime WebSocket protocol (specified here, built in M8)

Extends RFC-0001 §7's channel-tagged binary frames:

- **Channels:** `audio.in` (mic → runtime), `audio.out` (TTS → browser), plus the
  existing `control`, `text`, and `trace` channels.
- **Handshake:** negotiates codec (**PCM baseline; Opus optional** to cut droplet
  bandwidth) and sample rate.
- **Control frames:** `turn.start`, `turn.end`, `partial` (interim transcript),
  `final` (committed transcript), `tts.begin`, `tts.chunk`, `tts.end`, `duck`,
  and `cancel`.
- **Speech-gated uplink:** `audio.in` frames are sent **only while browser VAD
  detects speech**; the runtime never receives silence.
- **Barge-in:** handled locally in the browser as a reflex (duck playback the
  instant mic energy sustains) **and** signalled up with `cancel`, so the runtime
  aborts in-flight TTS synthesis via the `ExecutionContext` cancellation signal
  (RFC-0002) and the sidecar drops its queued audio.

### 5. Turn-taking and modes (browser-side)

Voice-activity detection and endpointing run **in the browser** (Silero-VAD via
ONNX/WASM; an RMS-energy detector is acceptable for a first increment). This keeps
silence off the wire (critical for the droplet) and makes barge-in a sub-network
local reflex.

Three mic states, with VAD as the shared endpointing engine in every listening
state:

| State | User action per turn | VAD's job | Barge-in |
|---|---|---|---|
| **Mic off** (default posture) | — (text only) | — | — |
| **Click-to-talk** | one click to start a turn | auto-**ends** the turn on trailing silence | n/a |
| **Always-on** | nothing — just talk | detects turn **start and end** | yes |

- **Endpointing:** relaxed, ~1 s trailing silence (configurable) so natural
  think-pauses do not clip the speaker.
- **Barge-in:** **duck-then-stop** — the assistant dips its volume when it hears
  the user and only fully stops if speech is sustained, so background noise and
  short backchannels ("mm-hm") do not cut it off. Duck threshold and hold time
  are configurable.
- **UI primitives:** a **mic toggle beside the text input**, an **always-on
  switch**, and a **voice-feature on/off** master (STT/TTS). Text and voice are
  *always both available* on any turn; the default posture is mic-off / text-only,
  and the always-on switch is what turns the experience into a no-clicking
  conversation. (The full UI is its own RFC; this RFC fixes only the control-frame
  contract those primitives bind to.)

### 6. Engines

- **STT — whisper.cpp, `base.en` default.** English-only lets us use the `.en`
  models, which beat multilingual at the same size; `base.en` transcribes a short
  turn in well under a second on CPU. `small.en` is an opt-in the hardware scan
  may recommend when there is headroom. Interim results come from whisper.cpp's
  streaming mode and are surfaced as `partial` frames.
- **TTS — Kokoro (ONNX, CPU) default.** Kokoro (82M params, `kokoro-onnx`) runs
  real-time on CPU and sounds markedly more natural than Piper. It is streamed
  **sentence-by-sentence** so first audio starts while the remainder synthesizes.
  It ships named **male and female English voices**, satisfying voice selection
  without any cloning.
- **Personalization — voicepack import + blend (in scope).** A Kokoro voice *is*
  a small voicepack embedding file. Zygos loads any voicepack file present in a
  `voices/` directory and lists it in the picker, and exposes **blending** (a
  weighted average of voicepack style vectors) so a user can dial in a custom
  voice from the built-ins. This is file-loading plus a weighted sum plus a
  picker — no GPU, no cloning pipeline — and answers "the voice I want" for every
  case short of impersonating a specific recording.
- **Piper fallback (hardware-gated floor).** If the hardware scan finds a machine
  that cannot run Kokoro in real time, the `text_to_speech` plugin falls back to
  **Piper** (more robotic, runs on nearly anything) so voice still works. If even
  Piper is infeasible, TTS is **honestly disabled** and the reason is surfaced in
  `zygos doctor`.
- **Clone-from-sample — deferred.** Turning a reference recording into a voice is
  the heavy, GPU-wanting problem this whole design avoids. It is deferred to a
  future GPU-gated RFC and is explicitly **not** a 2.0 requirement; the plugin
  boundary makes it a drop-in when that day comes.

### 7. Provisioning — fetch on first run

Zygos ships **no** third-party binaries and **no** per-platform builds. On first
run the installer:

1. Detects OS/arch.
2. Downloads the correct **pinned** upstream binaries (whisper.cpp, Piper) and
   **default models** (whisper `base.en`, Kokoro default voicepacks, one Piper
   voice) from their **official release URLs**.
3. **Verifies SHA-256** against pinned checksums; the download is resumable and
   retried with clear errors.
4. Health-checks each sidecar end to end.

An **offline pre-seed path** is documented: dropping the binaries and models into
`bin/` and `models/` yourself skips the fetch entirely — used for air-gapped
machines and for droplet images that fetch at build/provision time. Provisioning
state (binary present, model present, checksum verified) is part of each plugin's
health and is reported by `zygos doctor`.

### 8. Health, inspection, and hardware gating

- Each voice plugin reports: binary present · model present · sidecar alive ·
  device (cpu/gpu) · a latency sample. `zygos doctor --probe` exercises a real
  transcribe/synthesize round-trip. The runtime manifest lists the active engine
  **per direction**.
- This RFC **declares the gating inputs it needs** — real-time-TTS feasibility
  (Kokoro-vs-Piper floor), `small.en` eligibility, and future GPU-cloning
  eligibility — but **does not design the hardware scanner**, which is a separate
  RFC (Archon task `20203394`). Until that scanner exists, the floor decision may
  be made by an explicit config setting with Kokoro as the default attempt.

## Alternatives Considered

- **Voice models sharing the GPU with the LLM.** Rejected: this is the confirmed
  root-cause failure (VRAM contention, Ollama cold-reload thrash). CPU-only, out
  of the model manager, is the whole point.
- **In-process voice (threads / process pool inside the runtime).** Rejected:
  native crashes can still take down the runtime, model loads stall the event
  loop, and it blurs the "voice is a swappable plugin" boundary.
- **A single combined voice worker hosting both engines.** Rejected: it re-couples
  the two capabilities RFC-0003 deliberately split, and one crash takes down both
  directions. Per-engine sidecars keep "voice in, text out" and per-direction
  crash isolation.
- **Runtime-side or STT-engine-side VAD.** Rejected: runtime-side VAD streams all
  mic audio (including silence) up the wire — bad on a droplet — and makes barge-in
  eat a network round-trip; engine-side VAD couples turn-taking to the STT engine
  and breaks when the engine is swapped.
- **Hard-stop barge-in.** Rejected in favor of duck-then-stop: hard-stop lets a
  cough or a one-word backchannel cut off the assistant.
- **Bundling binaries/models in the installer (fetch-free first run).** Rejected:
  it forces redistribution of third-party binaries (licensing + upkeep),
  per-platform artifacts, or an on-machine compiler. Fetch-on-first-run with
  pinned checksums keeps Zygos one artifact at the cost of a first-run network
  dependency, which is mitigated (checksums, retries, offline pre-seed, doctor).
- **XTTS-v2 / Coqui for a natural cloned voice now.** Rejected for 2.0: heavy,
  GPU-wanting, reintroduces contention. Voicepack import + blend covers
  personalization on CPU; clone-from-sample is deferred.
- **WebRTC for the audio transport.** Deferred, not rejected: RFC-0001 §7 already
  notes STUN/TURN/SDP is heavy for self-hosted droplets. The channel-tagged binary
  frames keep the option of moving `audio.*` to a dedicated transport behind the
  same `VoiceService` interface if WS latency proves inadequate.

## Migration Plan

There is nothing to migrate from — no voice engine exists today. This RFC fills
in interfaces already published by RFC-0001 and RFC-0003, so it is purely
additive:

1. **M8** implements the `audio.in` / `audio.out` channels and the control frames
   as part of the FastAPI adapter + WebSocket protocol.
2. The **STT plugin + sidecar** lands first (input is the higher-value half and
   has no synthesis dependency), registering `SPEECH_TO_TEXT`.
3. The **TTS plugin + sidecar** (Kokoro, then Piper fallback) lands next,
   registering `TEXT_TO_SPEECH`, followed by voicepack import + blend.
4. **Provisioning** (fetch-on-first-run + offline pre-seed) is wired into the
   single-command installer, with health reported by `zygos doctor`.

Deployments that register neither plugin behave exactly as they do today; the UI
hides voice when the capabilities are absent.

## Risks

- **First-run network dependency.** A fetch can fail or stall. *Mitigation:*
  pinned checksums, resumable retried downloads, a documented offline pre-seed
  path, and clear `zygos doctor` reporting.
- **Native-binary supply chain.** Fetching binaries at runtime is an attack
  surface. *Mitigation:* official upstream URLs, pinned versions, SHA-256
  verification before first use.
- **CPU real-time budget on weak hardware.** Kokoro may not hit real time
  everywhere. *Mitigation:* the hardware-gated Piper floor, then honest disable
  with a reason in `zygos doctor`.
- **Barge-in false triggers.** Background noise interrupting the assistant.
  *Mitigation:* duck-then-stop with configurable threshold/hold, and speech-gated
  uplink.
- **Droplet WS audio latency** on high-RTT links. *Mitigation:* Opus codec
  option, VAD-gated uplink (no silence), and the WebRTC escape hatch behind the
  same `VoiceService` interface (RFC-0001 §7).
- **Native crash loops.** A sidecar that crashes on start. *Mitigation:*
  restart-with-backoff, and health that surfaces the crash rather than hanging.

## Acceptance Criteria

1. With the STT plugin registered, speaking a short English phrase over `audio.in`
   yields `partial` frames during speech and a `final` transcript within ~1 s of
   endpoint, produced by a whisper.cpp sidecar running `device=cpu`.
2. With the TTS plugin registered, a text turn produces `audio.out` beginning
   within one sentence's synthesis latency, from a Kokoro sidecar running
   `device=cpu`.
3. A deployment registering **only** `speech_to_text` transcribes input and emits
   **no** synthesized audio (voice in, text out), with no code change beyond
   plugin configuration.
4. While the assistant is speaking, sustained user speech **ducks then stops**
   playback and cancels in-flight synthesis; a brief cough or backchannel does
   **not**.
5. In always-on mode the user completes multiple turns **without clicking**, and
   no `audio.in` frame is sent during silence.
6. Selecting a different built-in voice, importing a voicepack file from `voices/`,
   and **blending** two voicepacks each change the synthesized voice — with no GPU
   and no cloning.
7. On a machine below the real-time-Kokoro threshold, TTS **falls back to Piper**;
   where even Piper is infeasible, TTS is **disabled** with the reason shown by
   `zygos doctor`.
8. A killed sidecar is **restarted** by its plugin; the runtime does not crash,
   and the outage is visible in health.
9. First run on a clean machine **fetches** the correct binaries and models,
   **verifies checksums**, and passes `zygos doctor --probe`; pre-seeding `bin/`
   and `models/` skips the fetch.
10. The runtime manifest and `zygos doctor` report the active engine, device, and
    provisioning state **per direction**.

## Architectural Impact

- **Coupling.** Runtime↔sidecar coupling is a **narrow, versioned transport
  contract** (length-prefixed control/PCM frames), not a code dependency. The
  runtime depends on `VoiceService` and the two capabilities — both already
  published — never on a specific engine. **No runtime dependency on the UI**: the
  browser drives turn-taking and speaks only the control-frame protocol.
- **Hidden state.** The sidecars are external OS processes — genuine hidden state.
  This RFC makes them **visible at the service boundary**: liveness, device,
  provisioning, and latency are snapshotable state (RFC-0002) surfaced through
  RFC-0003 health, `zygos doctor`, and the manifest. State the console cannot see
  would be the architecture bug; here it can.
- **Service boundaries.** No prior boundary is bypassed. This RFC *fills in*
  seams RFC-0001 (`VoiceService`, §7 frames) and RFC-0003 (the two capabilities)
  deliberately left open, and honors RFC-0002's cancellation model for barge-in.
- **Constitution.** Consistent with local-first and "the runtime never depends on
  the UI." Voice is optional: with no plugin registered, the runtime core is
  unchanged and the feature is **removable** without effect.
- **Independent testability.** Sidecars are testable against the IPC contract in
  isolation; `VoiceService` is mockable so runtime and UI can be tested without a
  real engine; the browser VAD/turn-taking is testable against the control-frame
  protocol without a runtime.
- **New service?** No new runtime *service* — the engines are **plugins** behind
  an existing service interface, plus two external sidecar processes they own.
