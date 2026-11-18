# RFC-0009: Vision Input — Images and PDFs in the Chat

- **Status:** Draft — **rewritten 2026-11-04.** The original (2026-07-13) covered
  per-turn model selection, text-specialist routing, model residency, vision input
  and image generation. Selection, routing and residency moved to
  [RFC-0013](RFC-0013-Model-Picker-Profiles-and-Task-Routing.md) and are built
  (phases 1–2). Image generation moved to
  [RFC-0015](RFC-0015-MCP-Client-Connecting-to-MCP-Servers.md): images are made by
  MCP tools (ComfyUI's MCP server, locally or on a user-run RunPod pod), so the
  original `ImageGenerator` contract is dropped. This RFC now covers **vision input
  only**. The earlier text is in git history (`git log --follow -- <this file>`;
  the file was named `RFC-0009-Model-Routing-and-Multimodal-Capabilities.md` until
  2026-11-17).
- **Author:** Zygos maintainers
- **Created:** 2026-07-13 (rewritten 2026-11-04)
- **Governs:** how a user gives Zygos an **image or a PDF** in the chat (drag and
  drop, paste, a file button), how the message thread carries it, which model reads
  it (a vision-capable default, a model the user marks for images, an OCR model for
  scanned PDFs, or a vision model that describes the image for a text-only default),
  how text PDFs are read without any model, what happens when nothing can read the
  attachment, and how each choice is shown.
- **Depends on:**
  [RFC-0013](RFC-0013-Model-Picker-Profiles-and-Task-Routing.md) (profiles with
  `capabilities.vision` and `specialty` `vision`/`ocr`; the saved-choices record;
  the per-turn pinned route; residency),
  [RFC-0001](RFC-0001-Service-Architecture.md) (`Message` typing, the `Provider`
  contract), [RFC-0007](RFC-0007-Session-Protocol-and-Turn-Loop.md) (the session
  socket and turn frames), [RFC-0011](RFC-0011-React-UI-Frontend-Architecture.md)
  (the chat surface), [RFC-0014](RFC-0014-Inference-Backends-llama-cpp-and-vLLM.md)
  (llama.cpp's `--mmproj` vision projector).
- **Amends (additively):** RFC-0001 §7 — a `Message` may carry **attachment parts**
  beside its text; RFC-0013's saved choices gain an optional **image model** and
  **OCR model** (§4); RFC-0003 — the `VISION` capability slot is filled by
  "a routable vision-capable model exists" rather than by a separate service.
- **Does not govern:** image generation (RFC-0015, via MCP tools); audio input
  (RFC-0005; Gemma native audio is its own work); documents other than PDF
  (later); choosing the default model (RFC-0013).
- **Implementation status:** not started. Archon `62a2f13b` (re-pointed to this scope).

## Summary

Drag an image or a PDF into the chat and ask about it — "what's wrong with this
wiring?", "write me a prompt that would produce an image like this", "summarise this
report". Zygos sends the image to a model that can see: the default if it has vision,
otherwise a model the user marks for images. A **text PDF** is read locally with no
model at all. A **scanned PDF** goes to an **OCR model** if the user has one, and to a
vision model if not. If the default can't see and nothing else is marked, any
installed vision model **describes** the image and the default answers from that
description. If no model can read it, Zygos says so — an attachment is never quietly
dropped. Every choice is shown in the trace and on the reply ("answered by …").

## Motivation

Users share screenshots, photos and documents constantly; a local assistant that can
only take text is missing the most common thing people hand it. The pieces mostly
exist now: RFC-0013 profiles already record whether a model has vision and whether it
is an OCR model; per-turn routes and residency are built; Ollama, vLLM, llama.cpp
(with a projector) and the cloud providers all accept images. What's missing is a way
to attach, a message type that carries the attachment, and the rule for which model
reads it.

Following the maintainer's rule (model-dependent features are a user choice gated on a
declared capability, never a hard-wired model), nothing here names a model: the user's
own models, by their profiles, decide.

## Problem Statement

1. The chat has no way to attach a file; `Message.content` is text only.
2. No rule says which model reads an image when the default can't.
3. Scanned PDFs need OCR, which general vision models do less well than OCR models.
4. Text PDFs don't need a model at all, but nothing reads them.
5. Later turns in the same conversation may be answered by a model that can't see
   the earlier image.

## Proposed Design

### 1. Attaching

- The chat accepts **drag and drop**, **paste** and a **file button**; voice turns
  don't attach.
- Accepted: PNG, JPEG, WebP, GIF (first frame) and PDF. Caps: 20 MB per file, 10 files
  per message, PDFs up to 100 pages; over a cap → refused before sending, with the
  reason. *(Values are starting points.)*
- Files upload over HTTP (`POST /sessions/{id}/attachments`) and are stored under
  `.zygos/attachments/<session>/`; the user message then refers to them by id. They
  are never sent anywhere except to the model that reads them (local, or a cloud model
  the user chose — the existing cloud labelling applies).
- The chat shows each attachment as a thumbnail (images) or a name + page count
  (PDFs), with a remove button before sending.

### 2. The thread

`Message` gains `attachments: tuple[AttachmentRef, ...]` (id, kind `image`/`pdf`,
mime, name, size, pages). The text stays in `content`. Providers that can take images
get them in their own format (Ollama `images`, OpenAI-style `image_url` parts for vLLM
and llama.cpp, Anthropic image blocks); a provider without vision never receives
image bytes (§3 decides first).

### 3. Which model reads it

Per turn, when the user message carries attachments (the turn's pinned route from
RFC-0013 §5 is decided **with** this rule, once, at turn start):

1. **Images.** If the default (the turn's pinned route) has `capabilities.vision` →
   it answers the whole turn, image included.
2. Else if the user marked an **image model** (§4) and it is routable → that model
   answers the whole turn.
3. Else if **any** installed, routable model has `capabilities.vision` (first by the
   Models page order) → it **describes** each image (a fixed, short instruction:
   describe everything visible, transcribe any text), and the default answers from
   the descriptions. The reply says "image described by <model>".
4. Else → no model reads it: the turn proceeds with a notice in the thread and the
   chat ("No model here can see images — add one with vision, e.g. on the Models
   page"), and the attachment stays on the message.

**PDFs**, per file:

- Text is extracted **locally** (no model), page by page.
- A page with no extractable text is **scanned**: it is rendered to an image and sent
  to the **OCR model** (§4) if one is marked or installed (`specialty: ocr`), else
  treated as an image under the rules above. The extracted text goes into the thread
  labelled by page.
- A large text PDF that won't fit the answering model's context is cut to fit with a
  notice ("pages 1–34 of 120 included"); retrieval over long documents is later.

The choice is recorded on the turn: `turn.end.model` names the answering model; a
`vision.read` trace event names who read each attachment and how (`direct`,
`described`, `ocr`, `text`, `none`) and is shown in Inspect.

**Details of the rule** *(my calls)*:

- **"The default"** is the turn's pinned route: the saved default, or with none saved
  the first eligible configured route (`CONFIG_ORDER` → `first_eligible()`).
- **Fallback mid-turn.** If the router falls back (RFC-0013 §5) to a model without
  vision, that model gets the description if one was made, else a placeholder, plus a
  notice; image bytes never reach it.
- **Turn paths.** Image turns use the tools loop or direct streaming as today. The
  reasoning (RDT) path takes text only, so on that path images are described first
  (rule 3's describe step) and the description goes into its input.
- **Tools.** If the model answering an image turn lacks `capabilities.tools`, the turn
  runs without tools and says so.
- **Where vision capability comes from.** Ollama (`/api/show`) and GGUF projectors as
  today. vLLM and cloud models have no automatic source, so the Models page gets
  **"Has vision" / "OCR model"** marks the user sets on any row (stored as
  `source: user` profile values, RFC-0013 §2). Until marked, they count as text-only —
  shown on the row ("vision unknown — mark it if this model can see").

### 4. Choosing an image model and an OCR model

RFC-0013's saved choices gain `image_model` and `ocr_model` (both optional). The
Models page offers "Use for images" on vision-capable rows and "Use for scanned PDFs"
on OCR rows, with the same fit check and confirm as "Set as default". Both are read
once per turn, as the default is. Reset buttons clear them.

### 5. Later turns

The image stays in the thread. A later turn answered by a vision-capable model gets
it again; a later turn answered by a text-only model gets the description if one was
made, otherwise a placeholder (`[image: wiring.jpg — not visible to this model]`).
Text extracted from PDFs stays as text. *(Re-sending images costs tokens; a cap on how
many past images are re-sent — 4 — keeps long conversations bounded.)*

### 6. Residency

Steps 2 and 3 can load a second local model in one turn. The vision model is loaded
through RFC-0013 residency like any other (one at a time, no eviction mid-turn,
"loading <model>…" shown). For step 3 on a small GPU this means a swap and a swap back;
the trace shows both, and the Models page notes that a vision-capable default avoids
it.

## Alternatives Considered

- **Always describe-then-answer.** Rejected as the default: a vision-capable default
  answers better from the image itself; describing stays the fallback.
- **A separate `VisionAnalyzer` service** (the original design). Rejected: every
  backend Zygos uses already accepts images on chat; a capability check on the
  profile is enough.
- **Send scanned pages to a general vision model.** Kept only as the fallback; OCR
  models transcribe better (maintainer).
- **OCR everything, including text PDFs.** Rejected: slower and less exact than the
  text already in the file.

## Migration Plan

Additive; with no attachments behaviour is exactly today's. Phases:

1. **Images:** attach (UI + upload endpoint), `Message.attachments`, provider image
   formats, rules 1–4, image model choice, later-turn handling, trace/Inspect.
2. **PDFs:** local text extraction, scanned-page detection and rendering, OCR model
   choice and routing, context cut notice.

## Risks

- **Wrong capability data** (a profile says vision, the model can't): mitigated by
  profile sources being shown and editable, and a provider error falling back per
  turn (RFC-0013).
- **Swap cost on small GPUs** for describe-then-answer: shown, and avoidable by a
  vision-capable default.
- **Large files and context overflow:** caps and the cut notice.
- **Malicious files** (PDF parsers): extraction runs with a pure-Python reader and
  page/size caps; rendering uses a maintained library; failures become a notice.

## Acceptance Criteria

1. Images and PDFs can be attached by drag and drop, paste and button, are refused
   over the caps with the reason, and are stored only locally.
2. With a vision-capable default, an image turn is answered by it with the image.
3. With a text-only default and an image model chosen, the image model answers that
   turn; the next text-only turn goes back to the default.
4. With a text-only default, no image model, and some vision model installed, the
   image is described by it and the default answers; the reply says so.
5. With no vision model, the turn proceeds with the notice and the attachment is kept.
6. A text PDF is read with no model; a scanned page goes to the OCR model when there
   is one, else follows the image rules; each read is in the trace.
7. Later turns resend images only to vision-capable models (at most 4) and give
   text-only models the description or placeholder.
8. With no attachments, all existing tests and behaviour are unchanged.

## Architectural Impact

- **Coupling.** The turn loop gains one decision at turn start; providers gain an
  image encoding each; no new service.
- **Hidden state.** None: attachments are files under `.zygos/attachments/`; every
  routing choice is a trace event.
- **Removability.** With the endpoint and UI removed, `Message.attachments` stays empty
  and nothing else changes.
