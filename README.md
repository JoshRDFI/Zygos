# Zygos v1 (TypeScript CLI)

> ⚠️ **This is the v1 branch — deprecated.** Zygos v1 is the stable TypeScript
> CLI reference implementation. It is being wound down (final bug fixes only,
> then frozen). **Active development is Zygos v2** (Python, self-hosted web app
> with voice) on the [`main` branch](https://github.com/JoshRDFI/Zygos/tree/main).
> New users who want the current direction should start there.

**Run AI on your terms — private or public, and always inspectable.**

Zygos is an open, **local-first AI runtime you host yourself**. Point it at a private
local model (Ollama, vLLM) or a public provider (OpenAI, Anthropic) — your choice, and
you can see which one handled every request. Your memory and history stay in a local
SQLite database on your machine. Nothing phones home.

This v1 runtime is a command-line tool. It is complete and usable, but no longer receives
new features — see [`main`](https://github.com/JoshRDFI/Zygos/tree/main) for v2.

## Getting just v1 (without the rest of the repo)

The cleanest way to get **only** v1 — no v2 history or files — is to download this
branch directly:

- **Download ZIP:** the `v1` branch → *Code ▸ Download ZIP* on GitHub, or
- **degit:** `npx degit JoshRDFI/Zygos#v1 zygos-v1`

A `git clone --single-branch --branch v1` also gives a pure-v1 working tree, but (because
history is shared) still downloads older repository history. Use the ZIP/degit path if you
want the smallest, v1-only download.

## Quick start (local)

**Prerequisites:** [Node.js](https://nodejs.org), and [Ollama](https://ollama.com)
running locally with a model pulled (for example, `ollama pull qwen3:8b`).

```bash
# from a v1 checkout (see "Getting just v1" above)
npm install
cp .env.example .env      # Ollama is the default; no API key needed for the local path
npm run verify            # confirms the runtime is wired correctly
npm run dev -- "Hello Zygos"
```

To use a public provider instead, set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in `.env`
and select it in `config/default.yaml`. For the full walkthrough, see
[docs/v1/QUICKSTART.md](./docs/v1/QUICKSTART.md).

## Documentation

- [v1 Guides](./docs/v1/) — Quick Start, Configuration, Examples, and subsystem guides
  (provider hardening, RDT reasoning, context management, tools, learning, interviewer)
- [Vision](./VISION.md) · [Compatibility](./COMPATIBILITY.md) ·
  [Constitution](./CONSTITUTION.md) · [Style Guide](./STYLE_GUIDE.md)

For the v2 architecture, roadmap, RFCs, and ADRs, see the
[`main` branch](https://github.com/JoshRDFI/Zygos/tree/main).

## About the name

**Zygos** (ζυγός) is Ancient Greek for **yoke**, **coupling**, or **joining** — binding
independent forces (providers, tools, reasoning, memory) into coordinated, balanced
motion.

## License

Apache-2.0 — see [LICENSE](./LICENSE).
