# Zygos v2 Milestone 1: Backend Foundation (Config, Plugins, Bootstrap)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the Python v2 backend skeleton with a working ConfigService, config-declared plugin resolution, and a composition root — RFC-0001 migration step 1.

**Architecture:** Pure-Python runtime core under `backend/zygos/` with zero web-framework imports (RFC-0001 §1). Pydantic v2 models validate declarative YAML config; a plugin resolver turns config-declared `"module:Class"` strings into types; `bootstrap.build_runtime()` is the only place concrete implementations are assembled (RFC-0001 §3). Constitution defaults (manual learning approval, fail-fast primary credentials) are encoded in the schema, ported from the v1 Stage-0 fixes.

**Tech Stack:** Python 3.12+, Pydantic ≥2.7, PyYAML ≥6.0, pytest ≥8.0.

## Global Constraints

- Python `>=3.12` (ZYGOS_VISION.md tech stack).
- Runtime core (`zygos/*` except a future `zygos/api`) must never import `fastapi`, `starlette`, or `uvicorn` (RFC-0001 §1). Enforced by the architecture guard test in Task 8; import-linter replaces it in the FastAPI-adapter milestone when `zygos/api` exists.
- Learning defaults MUST be `approval_mode="manual"`, `auto_apply_low_risk=False` (CONSTITUTION.md; RFC-0001 §8, acceptance criterion 7).
- Missing API key on the **primary** route (config and env both empty) MUST raise at load; fallback routes warn (RFC-0001 §8).
- Default primary route is keyless local-first: `ollama` / `llama3.1:8b` (matches v1 `loader.ts`).
- v1 (`src/`, TypeScript) is frozen — this plan never touches it.
- TDD for every task: failing test first, minimal code, green, commit.
- All commands below run from `/home/sage/zygos/backend` unless stated otherwise.

---

### Task 1: Backend package scaffold

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/zygos/__init__.py`
- Create: `backend/zygos/config/__init__.py`
- Create: `backend/zygos/plugins/__init__.py`
- Create: `backend/zygos/runtime/__init__.py`
- Create: `backend/zygos/services/__init__.py`
- Test: `backend/tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: importable `zygos` package, `zygos.__version__: str`, a `.venv` with dev deps, pytest wired to `backend/tests/`.

- [ ] **Step 1: Create the package layout and pyproject**

`backend/pyproject.toml`:

```toml
[project]
name = "zygos"
version = "2.0.0a0"
description = "Zygos AI runtime (v2, Python)"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.7",
    "PyYAML>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["zygos*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`backend/zygos/__init__.py`:

```python
"""Zygos AI runtime, version 2 (RFC-0001)."""

__version__ = "2.0.0a0"
```

The four subpackage `__init__.py` files (`config`, `plugins`, `runtime`, `services`) each contain only a one-line docstring, e.g. `"""Configuration schema and loading (RFC-0001 §3, §8)."""`.

- [ ] **Step 2: Write the failing smoke test**

`backend/tests/test_smoke.py`:

```python
import zygos


def test_package_importable_and_versioned():
    assert zygos.__version__ == "2.0.0a0"
```

- [ ] **Step 3: Create the venv, install, verify the test fails before install and passes after**

```bash
cd /home/sage/zygos/backend
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest tests/test_smoke.py -v
```

Expected: `1 passed`. (The RED here is trivial — before `pip install -e`, `import zygos` fails with ModuleNotFoundError; you can verify with the system python if desired.)

- [ ] **Step 4: Add backend venv/cache ignores to the repo .gitignore**

Append to `/home/sage/zygos/.gitignore`:

```
# Python (backend v2)
backend/.venv/
__pycache__/
*.egg-info/
.pytest_cache/
```

- [ ] **Step 5: Commit**

```bash
cd /home/sage/zygos
git add backend/ .gitignore
git commit -m "feat(v2): scaffold backend package layout per RFC-0001"
```

---

### Task 2: Error hierarchy and config schema with constitution defaults

**Files:**
- Create: `backend/zygos/errors.py`
- Create: `backend/zygos/config/schema.py`
- Test: `backend/tests/config/test_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `zygos.errors.ZygosError(Exception)` — base with `code: str` attribute; `ConfigError(ZygosError)` with `code = "config_invalid"`; `PluginError(ZygosError)` with `code = "plugin_resolution_failed"`.
  - `zygos.config.schema.ProviderRoute(BaseModel)` — `provider: str`, `model: str`, `weight: float = 1.0`.
  - `zygos.config.schema.ProviderCredential(BaseModel)` — `enabled: bool = True`, `api_key: str | None = None`, `require_api_key: bool | None = None`.
  - `zygos.config.schema.ProvidersConfig(BaseModel)` — `primary: ProviderRoute` (default ollama/llama3.1:8b), `fallbacks: list[ProviderRoute] = []`, `credentials: dict[str, ProviderCredential] = {}`; rejects duplicate provider+model routes.
  - `zygos.config.schema.LearningConfig(BaseModel)` — `enabled: bool = True`, `approval_mode: Literal["manual", "auto", "optional_human"] = "manual"`, `auto_apply_low_risk: bool = False`.
  - `zygos.config.schema.ZygosConfig(BaseModel)` — `providers: ProvidersConfig`, `learning: LearningConfig`, `plugins: dict[str, dict[str, str]] = {}` (kind → name → `"module:Class"`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/config/test_schema.py`:

```python
import pytest
from pydantic import ValidationError

from zygos.config.schema import ZygosConfig


def test_defaults_are_local_first_and_constitution_compliant():
    config = ZygosConfig()
    assert config.providers.primary.provider == "ollama"
    assert config.providers.primary.model == "llama3.1:8b"
    # CONSTITUTION.md: self-improvement is proposal-based, never autonomous
    assert config.learning.approval_mode == "manual"
    assert config.learning.auto_apply_low_risk is False
    assert config.plugins == {}


def test_duplicate_provider_routes_rejected():
    with pytest.raises(ValidationError, match="[Dd]uplicate provider route"):
        ZygosConfig.model_validate(
            {
                "providers": {
                    "primary": {"provider": "openai", "model": "gpt-4o-mini"},
                    "fallbacks": [{"provider": "openai", "model": "gpt-4o-mini"}],
                }
            }
        )


def test_unknown_top_level_keys_rejected():
    with pytest.raises(ValidationError):
        ZygosConfig.model_validate({"providres": {}})  # typo must not pass silently
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/config/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zygos.config.schema'`

- [ ] **Step 3: Write the implementation**

`backend/zygos/errors.py`:

```python
"""Unified error hierarchy (RFC-0001 §7)."""


class ZygosError(Exception):
    """Base for all runtime errors; carries a stable machine-readable code."""

    code: str = "zygos_error"


class ConfigError(ZygosError):
    code = "config_invalid"


class PluginError(ZygosError):
    code = "plugin_resolution_failed"
```

`backend/zygos/config/schema.py`:

```python
"""Declarative configuration schema (RFC-0001 §3, §8)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProviderRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    weight: float = 1.0


class ProviderCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    api_key: str | None = None
    require_api_key: bool | None = None


class ProvidersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: ProviderRoute = Field(
        default_factory=lambda: ProviderRoute(provider="ollama", model="llama3.1:8b")
    )
    fallbacks: list[ProviderRoute] = Field(default_factory=list)
    credentials: dict[str, ProviderCredential] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_duplicate_routes(self) -> "ProvidersConfig":
        seen: set[tuple[str, str]] = set()
        for route in [self.primary, *self.fallbacks]:
            key = (route.provider, route.model)
            if key in seen:
                raise ValueError(f"Duplicate provider route detected: {route.provider}:{route.model}")
            seen.add(key)
        return self


class LearningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    # CONSTITUTION.md: self-improvement is proposal-based, never autonomous.
    approval_mode: Literal["manual", "auto", "optional_human"] = "manual"
    auto_apply_low_risk: bool = False


class ZygosConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    # plugin kind -> plugin name -> "module.path:ClassName" (RFC-0001 §3)
    plugins: dict[str, dict[str, str]] = Field(default_factory=dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/config/test_schema.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/sage/zygos
git add backend/zygos/errors.py backend/zygos/config/schema.py backend/tests/config/test_schema.py
git commit -m "feat(v2): config schema with constitution-compliant defaults"
```

---

### Task 3: Environment placeholder resolution

**Files:**
- Create: `backend/zygos/config/env.py`
- Test: `backend/tests/config/test_env.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `zygos.config.env.resolve_env_placeholders(value: object) -> object` — recursively walks dicts/lists/strings; a string exactly of the form `${VAR_NAME}` becomes `os.environ["VAR_NAME"]` or `None` when unset; everything else passes through unchanged. (Same semantics as v1 `loader.ts:resolveEnvPlaceholders`.)

- [ ] **Step 1: Write the failing tests**

`backend/tests/config/test_env.py`:

```python
from zygos.config.env import resolve_env_placeholders


def test_placeholder_resolves_from_environment(monkeypatch):
    monkeypatch.setenv("ZYGOS_TEST_KEY", "sekrit")
    assert resolve_env_placeholders("${ZYGOS_TEST_KEY}") == "sekrit"


def test_missing_placeholder_resolves_to_none(monkeypatch):
    monkeypatch.delenv("ZYGOS_TEST_KEY", raising=False)
    assert resolve_env_placeholders("${ZYGOS_TEST_KEY}") is None


def test_non_placeholder_strings_and_scalars_pass_through():
    assert resolve_env_placeholders("plain") == "plain"
    assert resolve_env_placeholders("prefix ${NOT_WHOLE}") == "prefix ${NOT_WHOLE}"
    assert resolve_env_placeholders(42) == 42


def test_recurses_into_dicts_and_lists(monkeypatch):
    monkeypatch.setenv("ZYGOS_TEST_KEY", "sekrit")
    value = {"credentials": {"openai": {"api_key": "${ZYGOS_TEST_KEY}"}}, "routes": ["${ZYGOS_TEST_KEY}"]}
    resolved = resolve_env_placeholders(value)
    assert resolved["credentials"]["openai"]["api_key"] == "sekrit"
    assert resolved["routes"] == ["sekrit"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/config/test_env.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zygos.config.env'`

- [ ] **Step 3: Write the implementation**

`backend/zygos/config/env.py`:

```python
"""``${ENV_VAR}`` placeholder resolution, ported from v1 loader semantics."""

import os
import re

_PLACEHOLDER = re.compile(r"^\$\{([A-Za-z0-9_]+)\}$")


def resolve_env_placeholders(value: object) -> object:
    if isinstance(value, str):
        match = _PLACEHOLDER.match(value)
        if match is None:
            return value
        return os.environ.get(match.group(1))
    if isinstance(value, list):
        return [resolve_env_placeholders(item) for item in value]
    if isinstance(value, dict):
        return {key: resolve_env_placeholders(item) for key, item in value.items()}
    return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/config/test_env.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/sage/zygos
git add backend/zygos/config/env.py backend/tests/config/test_env.py
git commit -m "feat(v2): env placeholder resolution for config values"
```

---

### Task 4: YAML config loader

**Files:**
- Create: `backend/zygos/config/loader.py`
- Test: `backend/tests/config/test_loader.py`

**Interfaces:**
- Consumes: `ZygosConfig` (Task 2), `resolve_env_placeholders` (Task 3), `ConfigError` (Task 2).
- Produces: `zygos.config.loader.load_config(path: pathlib.Path | None = None) -> ZygosConfig` — no path → pure defaults; path → YAML parsed, env-resolved, validated. Validation failures raise `ConfigError` with a readable message. (Credential fail-fast is added in Task 5 inside this same function.)

- [ ] **Step 1: Write the failing tests**

`backend/tests/config/test_loader.py`:

```python
from pathlib import Path

import pytest

from zygos.config.loader import load_config
from zygos.errors import ConfigError


def test_no_path_returns_defaults():
    config = load_config()
    assert config.providers.primary.provider == "ollama"
    assert config.learning.approval_mode == "manual"


def test_yaml_file_overrides_defaults(tmp_path: Path):
    file = tmp_path / "config.yaml"
    file.write_text(
        "providers:\n"
        "  primary:\n"
        "    provider: vllm\n"
        "    model: qwen2.5-7b\n",
        encoding="utf-8",
    )
    config = load_config(file)
    assert config.providers.primary.provider == "vllm"
    assert config.providers.primary.model == "qwen2.5-7b"
    # untouched sections keep defaults
    assert config.learning.auto_apply_low_risk is False


def test_env_placeholders_resolved(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ZYGOS_TEST_KEY", "sekrit")
    file = tmp_path / "config.yaml"
    file.write_text(
        "providers:\n"
        "  credentials:\n"
        "    openai:\n"
        "      api_key: ${ZYGOS_TEST_KEY}\n",
        encoding="utf-8",
    )
    config = load_config(file)
    assert config.providers.credentials["openai"].api_key == "sekrit"


def test_invalid_config_raises_config_error(tmp_path: Path):
    file = tmp_path / "config.yaml"
    file.write_text("providers:\n  primary:\n    provider: 42\n    model: []\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(file)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/config/test_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zygos.config.loader'`

- [ ] **Step 3: Write the implementation**

`backend/zygos/config/loader.py`:

```python
"""Config loading: YAML -> env resolution -> validation (RFC-0001 §3)."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from zygos.config.env import resolve_env_placeholders
from zygos.config.schema import ZygosConfig
from zygos.errors import ConfigError


def load_config(path: Path | None = None) -> ZygosConfig:
    if path is None:
        return ZygosConfig()

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    resolved = resolve_env_placeholders(raw)
    try:
        return ZygosConfig.model_validate(resolved)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc']) or 'root'}: {issue['msg']}"
            for issue in error.errors()
        )
        raise ConfigError(f"Configuration validation failed: {details}") from error
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/config/test_loader.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/sage/zygos
git add backend/zygos/config/loader.py backend/tests/config/test_loader.py
git commit -m "feat(v2): YAML config loader with env resolution"
```

---

### Task 5: Fail-fast credential validation

**Files:**
- Modify: `backend/zygos/config/loader.py` (add `_validate_credentials`, call it from `load_config`)
- Test: `backend/tests/config/test_credentials.py`

**Interfaces:**
- Consumes: `load_config` (Task 4), `ConfigError` (Task 2).
- Produces: `load_config` now enforces RFC-0001 §8 — a route whose credential requires an API key (explicit `require_api_key: true`, or provider in `{"openai", "anthropic"}` by default) with no key in config **and** no `<PROVIDER>_API_KEY` env var: primary → `ConfigError`; fallback → `logging` warning on logger `"zygos.config"`, route still loads.

- [ ] **Step 1: Write the failing tests**

`backend/tests/config/test_credentials.py`:

```python
from pathlib import Path

import pytest

from zygos.config.loader import load_config
from zygos.errors import ConfigError


def _write(tmp_path: Path, body: str) -> Path:
    file = tmp_path / "config.yaml"
    file.write_text(body, encoding="utf-8")
    return file


def test_primary_route_missing_required_key_fails_fast(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    file = _write(
        tmp_path,
        "providers:\n"
        "  primary:\n"
        "    provider: openai\n"
        "    model: gpt-4o-mini\n"
        "  credentials:\n"
        "    openai:\n"
        "      enabled: true\n",
    )
    with pytest.raises(ConfigError, match="[Mm]issing api[_ ]?key for primary route"):
        load_config(file)


def test_primary_route_with_env_key_loads(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    file = _write(
        tmp_path,
        "providers:\n"
        "  primary:\n"
        "    provider: openai\n"
        "    model: gpt-4o-mini\n"
        "  credentials:\n"
        "    openai:\n"
        "      enabled: true\n",
    )
    config = load_config(file)
    assert config.providers.primary.provider == "openai"


def test_fallback_route_missing_key_warns_but_loads(tmp_path: Path, monkeypatch, caplog):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    file = _write(
        tmp_path,
        "providers:\n"
        "  primary:\n"
        "    provider: ollama\n"
        "    model: llama3.1:8b\n"
        "  fallbacks:\n"
        "    - provider: anthropic\n"
        "      model: claude-sonnet-4-6\n"
        "  credentials:\n"
        "    anthropic:\n"
        "      enabled: true\n",
    )
    with caplog.at_level("WARNING", logger="zygos.config"):
        config = load_config(file)
    assert len(config.providers.fallbacks) == 1
    assert any("anthropic" in record.message for record in caplog.records)


def test_keyless_local_first_defaults_load_without_any_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = load_config()
    assert config.providers.primary.provider == "ollama"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/config/test_credentials.py -v`
Expected: `test_primary_route_missing_required_key_fails_fast` FAILS (no error raised); the env-key and keyless tests may already pass — that is fine, they pin required behavior.

- [ ] **Step 3: Write the implementation**

Modify `backend/zygos/config/loader.py` — add imports, the validator, and the call:

```python
"""Config loading: YAML -> env resolution -> validation (RFC-0001 §3, §8)."""

import logging
import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from zygos.config.env import resolve_env_placeholders
from zygos.config.schema import ZygosConfig
from zygos.errors import ConfigError

_LOGGER = logging.getLogger("zygos.config")

# Providers that require an API key unless the credential says otherwise.
_KEYED_PROVIDERS = {"openai", "anthropic"}


def load_config(path: Path | None = None) -> ZygosConfig:
    if path is None:
        config = ZygosConfig()
        _validate_credentials(config)
        return config

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    resolved = resolve_env_placeholders(raw)
    try:
        config = ZygosConfig.model_validate(resolved)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc']) or 'root'}: {issue['msg']}"
            for issue in error.errors()
        )
        raise ConfigError(f"Configuration validation failed: {details}") from error
    _validate_credentials(config)
    return config


def _validate_credentials(config: ZygosConfig) -> None:
    """Fail fast on the primary route; warn on fallbacks (RFC-0001 §8)."""
    routes = [(config.providers.primary, True)] + [
        (route, False) for route in config.providers.fallbacks
    ]
    for route, is_primary in routes:
        credential = config.providers.credentials.get(route.provider)
        if credential is None or not credential.enabled:
            continue
        require_key = (
            credential.require_api_key
            if credential.require_api_key is not None
            else route.provider in _KEYED_PROVIDERS
        )
        env_key = f"{route.provider.upper()}_API_KEY"
        if require_key and not credential.api_key and not os.environ.get(env_key):
            if is_primary:
                raise ConfigError(
                    f"Missing api_key for primary route {route.provider}:{route.model}. "
                    f"Set providers.credentials.{route.provider}.api_key, export {env_key}, "
                    f"or set providers.credentials.{route.provider}.enabled: false."
                )
            _LOGGER.warning(
                "Missing api_key for fallback route %s:%s; this route will be "
                "skipped at runtime. Set providers.credentials.%s.api_key or %s.",
                route.provider,
                route.model,
                route.provider,
                env_key,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/config/ -v`
Expected: all config tests pass (schema 3, env 4, loader 4, credentials 4 = `15 passed`)

- [ ] **Step 5: Commit**

```bash
cd /home/sage/zygos
git add backend/zygos/config/loader.py backend/tests/config/test_credentials.py
git commit -m "feat(v2): fail-fast primary credential validation"
```

---

### Task 6: Plugin resolver

**Files:**
- Create: `backend/zygos/plugins/resolver.py`
- Test: `backend/tests/plugins/test_resolver.py`

**Interfaces:**
- Consumes: `PluginError` (Task 2).
- Produces:
  - `zygos.plugins.resolver.resolve_class(path: str) -> type` — `"package.module:ClassName"` → the class; raises `PluginError` for malformed paths, unimportable modules, or missing attributes.
  - `zygos.plugins.resolver.PluginRegistry` — `__init__(declarations: dict[str, dict[str, str]])` (the `ZygosConfig.plugins` mapping); `resolve(kind: str, name: str) -> type` raising `PluginError` for unknown kind/name; `list(kind: str) -> list[str]` returning declared names (empty list for unknown kind).

- [ ] **Step 1: Write the failing tests**

`backend/tests/plugins/test_resolver.py`:

```python
import pytest

from zygos.errors import PluginError
from zygos.plugins.resolver import PluginRegistry, resolve_class


def test_resolve_class_loads_a_real_class():
    cls = resolve_class("collections:OrderedDict")
    from collections import OrderedDict

    assert cls is OrderedDict


def test_resolve_class_rejects_malformed_path():
    with pytest.raises(PluginError, match="module.path:ClassName"):
        resolve_class("no-colon-here")


def test_resolve_class_rejects_missing_module():
    with pytest.raises(PluginError, match="zygos_no_such_module"):
        resolve_class("zygos_no_such_module:Thing")


def test_resolve_class_rejects_missing_attribute():
    with pytest.raises(PluginError, match="NoSuchClass"):
        resolve_class("collections:NoSuchClass")


def test_registry_resolves_declared_plugins():
    registry = PluginRegistry({"providers": {"ordered": "collections:OrderedDict"}})
    from collections import OrderedDict

    assert registry.resolve("providers", "ordered") is OrderedDict
    assert registry.list("providers") == ["ordered"]
    assert registry.list("voices") == []


def test_registry_rejects_unknown_plugin():
    registry = PluginRegistry({})
    with pytest.raises(PluginError, match="providers/unknown"):
        registry.resolve("providers", "unknown")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/plugins/test_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zygos.plugins.resolver'`

- [ ] **Step 3: Write the implementation**

`backend/zygos/plugins/resolver.py`:

```python
"""Config-declared plugin resolution (RFC-0001 §3).

Plugins are declared in config as ``kind -> name -> "module.path:ClassName"``.
Reading the config tells you exactly what code runs; nothing auto-activates.
"""

import importlib

from zygos.errors import PluginError


def resolve_class(path: str) -> type:
    module_path, _, attribute = path.partition(":")
    if not module_path or not attribute:
        raise PluginError(
            f"Invalid plugin path {path!r}: expected 'module.path:ClassName'."
        )
    try:
        module = importlib.import_module(module_path)
    except ImportError as error:
        raise PluginError(f"Cannot import plugin module {module_path!r}: {error}") from error
    try:
        return getattr(module, attribute)
    except AttributeError as error:
        raise PluginError(
            f"Module {module_path!r} has no attribute {attribute!r}."
        ) from error


class PluginRegistry:
    def __init__(self, declarations: dict[str, dict[str, str]]) -> None:
        self._declarations = declarations

    def resolve(self, kind: str, name: str) -> type:
        path = self._declarations.get(kind, {}).get(name)
        if path is None:
            raise PluginError(f"No plugin declared for {kind}/{name}.")
        return resolve_class(path)

    def list(self, kind: str) -> list[str]:
        return sorted(self._declarations.get(kind, {}))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/plugins/test_resolver.py -v`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/sage/zygos
git add backend/zygos/plugins/resolver.py backend/tests/plugins/test_resolver.py
git commit -m "feat(v2): config-declared plugin resolver and registry"
```

---

### Task 7: Composition root

**Files:**
- Create: `backend/zygos/runtime/bootstrap.py`
- Test: `backend/tests/runtime/test_bootstrap.py`

**Interfaces:**
- Consumes: `load_config` (Tasks 4–5), `PluginRegistry` (Task 6), `ZygosConfig` (Task 2).
- Produces:
  - `zygos.runtime.bootstrap.RuntimeAssembly` — frozen dataclass with `config: ZygosConfig` and `plugins: PluginRegistry`. Later milestones extend this with services; it stays construction-only (RFC-0001 risk: "composition root grows into a god-module").
  - `zygos.runtime.bootstrap.build_runtime(config_path: pathlib.Path | None = None) -> RuntimeAssembly`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/runtime/test_bootstrap.py`:

```python
import dataclasses
from pathlib import Path

from zygos.plugins.resolver import PluginRegistry
from zygos.runtime.bootstrap import RuntimeAssembly, build_runtime


def test_build_runtime_with_defaults():
    assembly = build_runtime()
    assert assembly.config.providers.primary.provider == "ollama"
    assert isinstance(assembly.plugins, PluginRegistry)


def test_build_runtime_wires_declared_plugins(tmp_path: Path):
    file = tmp_path / "config.yaml"
    file.write_text(
        "plugins:\n"
        "  providers:\n"
        "    ordered: 'collections:OrderedDict'\n",
        encoding="utf-8",
    )
    assembly = build_runtime(file)
    from collections import OrderedDict

    assert assembly.plugins.resolve("providers", "ordered") is OrderedDict


def test_assembly_is_immutable():
    assembly = build_runtime()
    try:
        assembly.config = None  # type: ignore[misc]
        raised = False
    except dataclasses.FrozenInstanceError:
        raised = True
    assert raised, "RuntimeAssembly must be a frozen dataclass"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/runtime/test_bootstrap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zygos.runtime.bootstrap'`

- [ ] **Step 3: Write the implementation**

`backend/zygos/runtime/bootstrap.py`:

```python
"""Composition root (RFC-0001 §3).

The ONLY module allowed to construct concrete service implementations.
It may only construct and connect — any logic beyond assembly is a
review-blocking smell.
"""

from dataclasses import dataclass
from pathlib import Path

from zygos.config.loader import load_config
from zygos.config.schema import ZygosConfig
from zygos.plugins.resolver import PluginRegistry


@dataclass(frozen=True)
class RuntimeAssembly:
    config: ZygosConfig
    plugins: PluginRegistry


def build_runtime(config_path: Path | None = None) -> RuntimeAssembly:
    config = load_config(config_path)
    return RuntimeAssembly(config=config, plugins=PluginRegistry(config.plugins))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/runtime/test_bootstrap.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/sage/zygos
git add backend/zygos/runtime/bootstrap.py backend/tests/runtime/test_bootstrap.py
git commit -m "feat(v2): composition root assembling config and plugin registry"
```

---

### Task 8: Architecture guard and CI

**Files:**
- Create: `backend/tests/test_architecture.py`
- Create: `.github/workflows/backend.yml` (repo root)

**Interfaces:**
- Consumes: the `zygos` package tree (all prior tasks).
- Produces: a test that fails the suite if any runtime-core module imports a web framework (RFC-0001 acceptance criterion 1, pytest-based until `zygos/api` exists — then import-linter replaces it), and a CI workflow running the backend suite on push/PR.

- [ ] **Step 1: Write the failing-proof architecture test**

`backend/tests/test_architecture.py`:

```python
"""RFC-0001 §1: the runtime core never imports web frameworks.

pytest-based guard; replaced by an import-linter contract in the
FastAPI-adapter milestone once ``zygos/api`` exists.
"""

import ast
from pathlib import Path

FORBIDDEN = {"fastapi", "starlette", "uvicorn"}
PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "zygos"


def _imported_top_level_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_runtime_core_never_imports_web_frameworks():
    offenders: list[str] = []
    for file in PACKAGE_ROOT.rglob("*.py"):
        if "api" in file.relative_to(PACKAGE_ROOT).parts:
            continue  # the adapter layer may import FastAPI
        imported = _imported_top_level_modules(file.read_text(encoding="utf-8"))
        if imported & FORBIDDEN:
            offenders.append(str(file))
    assert offenders == [], f"Runtime core imports web frameworks: {offenders}"
```

- [ ] **Step 2: Verify it passes now and fails when violated**

Run: `.venv/bin/pytest tests/test_architecture.py -v`
Expected: `1 passed`

Then prove the guard works: temporarily add `import fastapi  # noqa` to `backend/zygos/runtime/bootstrap.py`, re-run, confirm it FAILS listing `bootstrap.py`, then remove the line and confirm it passes again. (This is the RED for a guard test — it must be demonstrated capable of failing.)

- [ ] **Step 3: Add the CI workflow**

`.github/workflows/backend.yml`:

```yaml
name: backend

on:
  push:
    branches: [main]
    paths: ['backend/**', '.github/workflows/backend.yml']
  pull_request:
    paths: ['backend/**', '.github/workflows/backend.yml']

jobs:
  test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -e '.[dev]'
      - run: pytest -v
```

- [ ] **Step 4: Run the full backend suite**

Run: `.venv/bin/pytest -v` (from `backend/`)
Expected: all tests pass (smoke 1 + schema 3 + env 4 + loader 4 + credentials 4 + resolver 6 + bootstrap 3 + architecture 1 = `26 passed`)

- [ ] **Step 5: Commit**

```bash
cd /home/sage/zygos
git add backend/tests/test_architecture.py .github/workflows/backend.yml
git commit -m "feat(v2): architecture guard test and backend CI workflow"
```

---

## Out of Scope (later milestones, per RFC-0001 migration order)

- Providers + ModelService + RouterState (Milestone 2 — next plan)
- RDT engine, memory, tools, learning, workflows (Milestones 3–7)
- FastAPI adapter, WebSocket protocol, React UI, voice engines (Milestone 8+, separate RFCs)
- import-linter swap-in for the architecture guard (with the FastAPI adapter)
- v1 legacy-config migration (v2 config is a clean snake_case format; a converter can be an explicit later task if needed)
