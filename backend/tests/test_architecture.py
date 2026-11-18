"""RFC-0001 §1: the runtime core never imports web frameworks.

pytest-based guard; replaced by an import-linter contract in the
FastAPI-adapter milestone once ``zygos/api`` exists.
"""

import ast
from pathlib import Path

import pytest

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
        try:
            imported = _imported_top_level_modules(file.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            pytest.fail(f"Unparseable source {file}: {exc}")
        if imported & FORBIDDEN:
            offenders.append(str(file))
    assert offenders == [], f"Runtime core imports web frameworks: {offenders}"


def _imported_modules(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_providers_never_import_the_thinking_package():
    """RFC-0012: providers are the lower layer; zygos.thinking builds on them."""
    offenders = [
        str(file)
        for file in (PACKAGE_ROOT / "providers").rglob("*.py")
        if any(m == "zygos.thinking" or m.startswith("zygos.thinking.")
               for m in _imported_modules(file.read_text(encoding="utf-8")))
    ]
    assert offenders == [], f"providers import zygos.thinking: {offenders}"


def test_model_service_does_not_load_the_catalog_or_voice():
    """RFC-0013 §5: the turn-path model service stays light; the catalog
    (hardware probe, GGUF, voice state) sits above it."""
    import subprocess
    import sys

    code = (
        "import sys, zygos.services.model\n"
        "bad = sorted(m for m in sys.modules if m == 'zygos.models.catalog' or m == 'zygos.voice'"
        " or m.startswith('zygos.voice.'))\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=PACKAGE_ROOT.parent)
    assert out.stdout.strip() == ""


def test_local_providers_live_below_the_catalog():
    from zygos.models import catalog
    from zygos.providers import types

    assert catalog.LOCAL_PROVIDERS is types.LOCAL_PROVIDERS
    assert types.LOCAL_PROVIDERS == frozenset({"ollama", "llamacpp", "vllm", "fake"})


def test_build_runtime_does_not_import_secret_libraries():
    """RFC-0015 phase 0: the optional secrets extra is imported only when used."""
    import subprocess
    import sys

    code = (
        "import sys, tempfile, pathlib\n"
        "d = pathlib.Path(tempfile.mkdtemp())\n"
        "c = d / 'c.yaml'\n"
        "c.write_text(f\"personalization:\\n  db_path: '{d}/p.db'\\n\"\n"
        "             'providers:\\n  primary: {provider: fake, model: fake-1}\\n')\n"
        "import asyncio\n"
        "from zygos.runtime.bootstrap import build_runtime\n"
        "r = build_runtime(c)\n"
        "asyncio.run(r.aclose())\n"
        "print(','.join(m for m in ('keyring', 'cryptography') if m in sys.modules))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True, cwd=PACKAGE_ROOT.parent)
    assert out.stdout.strip() == ""
