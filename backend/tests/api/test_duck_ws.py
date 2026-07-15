from __future__ import annotations

import json

import yaml
from fastapi.testclient import TestClient

from zygos.api.app import create_app
from zygos.runtime.bootstrap import build_runtime


def test_turn_deps_carry_duck_config_defaults():
    app = create_app(build_runtime())
    assert app.state.turn_deps.duck_gain == 0.2
    assert app.state.turn_deps.duck_timeout_s == 2.0


def test_turn_deps_carry_duck_config_overrides(tmp_path):
    p = tmp_path / "z.yaml"
    p.write_text(yaml.safe_dump(
        {"voice": {"tts": {"duck_gain": 0.5}, "duck_timeout_s": 1.0}}))
    app = create_app(build_runtime(p))
    assert app.state.turn_deps.duck_gain == 0.5
    assert app.state.turn_deps.duck_timeout_s == 1.0
