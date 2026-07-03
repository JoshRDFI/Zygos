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
