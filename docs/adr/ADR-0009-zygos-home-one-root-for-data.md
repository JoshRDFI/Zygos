# ADR-0009: One Root for Zygos Data (`ZYGOS_HOME`)

**Status:** Accepted
**Date:** 2026-11-18

## Context

Every data path in the config (`memory.db_path`, `personalization.db_path`, `tools.workspace_root`, `models.profiles_dir`, the voice model folders) defaulted to a relative string such as `.zygos/memory.db`. A relative path means "relative to the folder you started Zygos from". The README workflow starts the server from `backend/`, so data landed in `backend/.zygos`. Starting the same install from the repo root, or from a service manager's working folder, silently created a second `.zygos` and the app looked empty: a split install.

The voice code also assumed a checkout layout for its model caches and GPU venv. The planned MCP client (phase 1) adds credentials and server state that must not depend on where a terminal happened to be open. An install made with `pip install` outside a checkout has no `backend/` folder at all.

## Decision

Zygos finds one **root** and puts all data at `<root>/.zygos/...`. The root is the first of:

1. `ZYGOS_HOME`, when set and non-empty. `~` is expanded; a relative value is resolved against the start folder once. The folder need not exist.
2. The checkout's `backend/` folder, when it holds a `pyproject.toml` whose `[project] name` is `zygos`. A missing, unreadable or other-named file falls through quietly.
3. A per-user folder: `$XDG_DATA_HOME/zygos` (only if set and absolute) or `~/.local/share/zygos` on Linux and others; `~/Library/Application Support/zygos` on macOS; `%LOCALAPPDATA%\zygos` (else `~/AppData/Local/zygos`) on Windows.

Path rule: an absolute value is unchanged, `~` is expanded, anything else becomes `<root>/<value>`. Schema defaults stay relative strings; they are resolved in `load_config`, including `load_config(None)`. Resolved: `memory.db_path`, `personalization.db_path`, `tools.workspace_root`, `models.profiles_dir`, `voice.stt.download_root`, `voice.tts.download_root` (when set), and `voice.tts.worker_python` (when set and it contains a path separator; a bare name like `python3` is left alone). Voice defaults that are not in the config (model caches, GPU venv) resolve the same way.

Not resolved: `models.ollama_models_dir`, URLs, and the `--config` argument itself. Sidecar processes get absolute `ZYGOS_*_DOWNLOAD_ROOT` values; `ZYGOS_HOME` is not passed to them.

Finding the root, loading config and `zygos doctor` create nothing. `zygos serve` creates the tools workspace when tools are enabled, as it did before. `zygos doctor` reports the root and where it came from (`zygos_home` line, source `ZYGOS_HOME`, `checkout` or `user data folder`).

## Consequences

- The README workflow does not move any data: from a checkout the root is `backend/`, so data stays in `backend/.zygos`.
- A relative path in a config file now resolves against the root, not the start folder. A `--config` file that said `.zygos/memory.db` and was run from elsewhere will point at the root's copy. The `--config` path itself is still read relative to the start folder.
- Droplets and services set `ZYGOS_HOME` (for example `/var/lib/zygos`) instead of relying on a working folder.
- A leftover `.zygos` folder in the start folder is now unused. `zygos doctor` (`stray_data_folder`, a warning) and the serve log say so, naming the root and the `ZYGOS_HOME=<folder>` setting that would use it instead. The warning fires only when that folder is a directory and differs from `<root>/.zygos`. Nothing is moved or deleted automatically.
- The test suite sets its own `ZYGOS_HOME` and never writes into the real `backend/.zygos`.

## Alternatives considered

- **B: Per-user data folder always.** Conventional and survives deleting the checkout, but the existing models, profiles and GPU venv would have to move once, and every dev checkout would share one install.
- **C: The config file's folder when `--config` is given, else A.** Two config files mean two installs, but it adds a rule to remember and `zygos mcp add` would need the same `--config` as the server.

(Also considered and dropped: keeping paths relative to the start folder and documenting "always start from `backend/`" leaves the split-install trap in place.)
