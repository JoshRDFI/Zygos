# Zygos

**Run AI on your terms — private or public, and always inspectable.**

AI increasingly handles your private conversations, your documents, your long-term
memory, and access to real tools on your system. Too often that means sending sensitive
context to services you can't see into, accepting agent behavior you can't audit, and
getting locked into a single provider.

Zygos is an open, **local-first AI runtime you host yourself**. Point it at a private
local model (Ollama, vLLM) or a public provider (OpenAI, Anthropic) — your choice, and
you can see which one handled every request. Your memory and history stay in a local
database on your machine. Nothing phones home. And Zygos is built to be *inspected*: you
can see the model, memory, and tools behind each answer. It's for people who want
capable AI without treating privacy, visibility, or control as optional.

## Where Zygos is today

Zygos comes in two runtimes: **v1**, the stable TypeScript CLI, now maintained on the
[`v1` branch](https://github.com/JoshRDFI/Zygos/tree/v1) (deprecated — final bug fixes
only), and **v2**, a Python migration toward a self-hosted web app with voice, in active
development on this (`main`) branch. The v2 runtime now **runs as a self-hosted server
with a live chat-and-tools turn loop over WebSocket** (start it with `zygos serve`), and a
**React web app** front of it carries live chat, read-only inspection panels, and **voice
in and out** (local Whisper/Kokoro engines, opt-in). Both are early — a few surfaces
(files, memory, model picker) are still placeholders — and the graphical UI keeps growing.
This README describes where Zygos is headed; the table marks what runs now versus what's
still being built.

|                | Today — v1 (TypeScript CLI)                     | In development — v2 (Python, self-hosted web app)   |
|----------------|-------------------------------------------------|----------------------------------------------------|
| **Models**     | Local (Ollama, vLLM) + public (OpenAI, Anthropic) | Same, routed by capability                        |
| **Your data**  | Local SQLite — history & context on your machine | Layered memory with local semantic recall          |
| **Tools**      | Tool framework (registry, permission checks, fallback) | Starter file / HTTP / shell tools, called by the model in the live turn loop with permission prompts |
| **Interface**  | Command line                                     | WebSocket server + turn loop **built**; React web UI with live chat and **voice I/O built** (early — some surfaces are placeholders) |
| **Inspection** | Provider & route metrics                          | Runtime manifest & health, surfaced in the web UI's Inspect / Doctor / Models / Tools panels; a fuller introspection console *(expanding)* |
| **Status**     | Stable; frozen (bug fixes only)                  | In active development — see the [roadmap](./ROADMAP.md) |

## Why Zygos

- **Private *or* public LLMs — your choice, made visible.** Run locally with Ollama or
  vLLM, or connect a public provider when you want to — and see which handled each
  request. *(today)*
- **Your data stays where you put it.** Memory and history live in a local SQLite
  database on your own machine or VM; there's no managed platform in the middle.
  *(today; the self-hosted web app is in development)*
- **Auditable, not opaque.** Inspect the model route, memory, and tools behind an
  answer — so you can verify what was used and what left your machine. *(partial today;
  a full introspection console is in development)*
- **Real tools, gated by you.** Zygos can read and write files, fetch the web, and run
  commands when a task needs them — but side-effecting tools ask before they act, and you
  can loosen or lock that down per tool in config. *(the starter tools run live in the v2
  turn loop; v1 provides the tool framework)*
- **No telemetry.** Zygos ships no analytics and no phone-home — nothing about your usage
  is collected or sent anywhere. *(today)*
- **Improvement you approve.** Zygos can propose new skills and refinements, but never
  changes its own behavior without human review and testing. *(today in v1; the v2
  service is planned)*
- **No lock-in.** Swap models, memory backends, tools, and providers without rebuilding —
  components bind to capabilities, not vendors. *(today)*
- **Voice, on your machine.** Local-first speech in and out — talk to Zygos hands-free and
  interrupt it mid-reply, with the assistant ducking then stopping when you speak over it.
  Local Whisper-family transcription and Kokoro synthesis run behind the same replaceable
  seam as everything else, opt-in and defaulting off. *(built — live in the web UI; real
  engines are opt-in, with optional cloud fallback planned)*

## What "private" means here

Privacy on Zygos means **your data — your conversations, history, memory, and documents —
stays yours and lives on your machine.** It does *not* mean the system is walled off from
the internet: reaching out is a normal capability you control (a public model, a web-fetch
tool you invoke), and Zygos is built so you can see every time it happens. You decide where
your data lives and what, if anything, is sent.

| Level                            | Setup                                          | Your data (history, memory, documents) | What reaches the network                                              |
|----------------------------------|------------------------------------------------|----------------------------------------|----------------------------------------------------------------------|
| **Fully local**                  | Local model (Ollama/vLLM) + local storage      | Stays on your machine                  | Nothing is *required* for chat or memory; a web-fetch or search tool reaches out only when you ask it to.\* |
| **Local storage, public model**  | Public LLM (OpenAI/Anthropic) + local storage  | Stays on your machine                  | The prompt/context you send to the chosen provider — plus any tool you invoke. |

\* Zygos can run its core chat and memory fully offline with a local model once it's
downloaded — a design goal of the local-first path (verify it for your configuration). A
tool you invoke — like fetching a web page you asked for — reaches the network by design;
that's a capability you control and can see, not a data leak.

## Quick start (v1 CLI, local)

The usable runtime today is the v1 CLI, which lives on the
[`v1` branch](https://github.com/JoshRDFI/Zygos/tree/v1). This path keeps everything local
with Ollama.

**Prerequisites:** [Node.js](https://nodejs.org), and [Ollama](https://ollama.com)
running locally with a model pulled (for example, `ollama pull qwen3:8b`).

```bash
# fetch v1 only — no v2 files or history (or download the v1 branch as a ZIP from GitHub):
npx degit JoshRDFI/Zygos#v1 zygos-v1
cd zygos-v1
npm install
cp .env.example .env      # Ollama is the default; no API key needed for the local path
npm run verify            # confirms the runtime is wired correctly
npm run dev -- "Hello Zygos"
```

To use a public provider instead, set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in `.env`
and select it in `config/default.yaml`. For the full v1 walkthrough, see the
[v1 branch guides](https://github.com/JoshRDFI/Zygos/tree/v1/docs/v1).

## How Zygos works

Zygos is a composable runtime — independent services for model routing, reasoning,
memory, tools, and tracing, wired together at one place and inspectable end to end. For a
readable tour of the subsystems and how they fit, see the
[Technical Overview](./TECHNICAL_OVERVIEW.md); for the authoritative design, see
[ARCHITECTURE.md](./ARCHITECTURE.md).

## Documentation

- [Technical Overview](./TECHNICAL_OVERVIEW.md) — how the system works
- [Architecture](./ARCHITECTURE.md) — the authoritative v2 design
- [Vision](./VISION.md) — why Zygos exists and where it's headed
- [Roadmap](./ROADMAP.md) — milestone-by-milestone status
- [Compatibility](./COMPATIBILITY.md) · [Constitution](./CONSTITUTION.md) · [Style Guide](./STYLE_GUIDE.md)
- [RFCs](./docs/rfcs/) · [ADRs](./docs/adr/) — the decision log
- [v1 Guides](https://github.com/JoshRDFI/Zygos/tree/v1/docs/v1) — the v1 (TypeScript CLI) docs, on the `v1` branch

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md) for branch
conventions, code standards, and the workflow.

Zygos is developed AI-native and deliberately so: architecture, review, and every
decision about what ships are the maintainer's; the code is primarily authored by Claude
(Anthropic) under that direction, reflected in the commit trailers.

## About the name

**Zygos** (ζυγός) is Ancient Greek for **yoke**, **coupling**, or **joining** — binding
independent forces (providers, tools, reasoning, memory) into coordinated, balanced
motion. It's the same idea the runtime embodies: many capabilities, one coherent,
inspectable system.

## License

Apache-2.0 — see [LICENSE](./LICENSE).
