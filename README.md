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

Zygos comes in two runtimes: **v1**, a stable TypeScript CLI you can use today, and
**v2**, a Python migration toward a self-hosted web app with voice. This README describes
where Zygos is headed; the table marks what runs now versus what's still being built.

|                | Today — v1 (TypeScript CLI)                     | Coming — v2 (Python, self-hosted web app)          |
|----------------|-------------------------------------------------|----------------------------------------------------|
| **Models**     | Local (Ollama, vLLM) + public (OpenAI, Anthropic) | Same, routed by capability                        |
| **Your data**  | Local SQLite — history & context on your machine | Layered memory with local semantic recall          |
| **Interface**  | Command line                                     | Web UI **and** voice *(in development)*             |
| **Inspection** | Provider & route metrics                          | Full introspection console *(in development)*       |
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
- **No telemetry.** Zygos ships no analytics and no phone-home — nothing about your usage
  is collected or sent anywhere. *(today)*
- **Improvement you approve.** Zygos can propose new skills and refinements, but never
  changes its own behavior without human review and testing. *(today in v1; the v2
  service is planned)*
- **No lock-in.** Swap models, memory backends, tools, and providers without rebuilding —
  components bind to capabilities, not vendors. *(today)*
- **Voice, on your machine.** Local-first speech in and out, with optional cloud fallback.
  *(in development)*

## Choose your privacy level

Zygos doesn't force an all-or-nothing choice. You decide how much stays local:

| Level                        | Setup                                   | What leaves your machine                                              |
|------------------------------|-----------------------------------------|----------------------------------------------------------------------|
| **Fully local**              | Local model (Ollama/vLLM) + local storage | Nothing, once the model is downloaded.\*                            |
| **Local storage, public model** | Public LLM (OpenAI/Anthropic) + local storage | Only the prompt/context you send to the chosen provider; history and memory stay local. |

\* Running fully offline is a design goal of the local-first path; verify it for your own
configuration before relying on it.

## Quick start (v1, local)

The usable runtime today is the v1 CLI. This path keeps everything local with Ollama.

**Prerequisites:** [Node.js](https://nodejs.org), and [Ollama](https://ollama.com)
running locally with a model pulled (for example, `ollama pull qwen3:8b`).

```bash
git clone https://github.com/JoshRDFI/Zygos.git
cd Zygos
npm install
cp .env.example .env      # Ollama is the default; no API key needed for the local path
npm run verify            # confirms the runtime is wired correctly
npm run dev -- "Hello Zygos"
```

To use a public provider instead, set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in `.env`
and select it in `config/default.yaml`. For the full walkthrough, see
[docs/v1/QUICKSTART.md](./docs/v1/QUICKSTART.md).

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
- [v1 Guides](./docs/v1/)

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
