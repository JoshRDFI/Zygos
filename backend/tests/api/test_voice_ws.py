"""Voice sidecar lifespan integration (Voice Cycle 1, Task 10).

Proves the FastAPI lifespan actually spawns the STT sidecar at startup and
kills it at shutdown when voice is enabled — mirroring the memory_service
resume/close pattern in `_lifespan`. Uses the real `fake` STT engine (a real
subprocess) so `snapshot().stt.alive` reflects genuine OS-level state, not a
mock.

Stability: Experimental (test-only).
"""

from __future__ import annotations

import dataclasses

import yaml
from fastapi.testclient import TestClient

from zygos.api.app import create_app
from zygos.runtime.bootstrap import build_runtime


def _voice_runtime(tmp_path, script=None):
    p = tmp_path / "zygos.yaml"
    p.write_text(yaml.safe_dump({"voice": {"enabled": True, "stt": {"engine": "fake"}}}))
    rt = build_runtime(p)
    # swap in a FakeProvider-backed model so turns are deterministic
    from zygos.providers.fake import FakeProvider
    from zygos.services.model import DefaultModelService
    from zygos.services.router import ProviderRouter, RouteChoice

    provider = FakeProvider(script=script or ["heard you"])
    model = DefaultModelService(ProviderRouter([RouteChoice("fake", "m")], {"fake": provider}))
    return dataclasses.replace(rt, model_service=model, memory_service=None)


def test_lifespan_starts_and_stops_sidecar(tmp_path):
    rt = _voice_runtime(tmp_path)
    app = create_app(rt)
    with TestClient(app):  # enters lifespan
        assert rt.voice_service.snapshot().stt.alive is True
    # after lifespan exit, sidecar is killed
    assert rt.voice_service.snapshot().stt.alive is False
