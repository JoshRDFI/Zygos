from zygos.runtime.bootstrap import build_runtime
from zygos.runtime.manifest import runtime_manifest


def test_manifest_voice_absent_when_off():
    m = runtime_manifest(build_runtime())
    assert m.voice is None


def test_manifest_reports_stt_direction_when_on(tmp_path):
    import yaml
    p = tmp_path / "zygos.yaml"
    p.write_text(yaml.safe_dump({"voice": {"enabled": True, "stt": {"engine": "fake"}}}))
    m = runtime_manifest(build_runtime(p))
    assert m.voice is not None
    assert m.voice.stt is not None
    assert m.voice.stt.engine == "fake"
    assert m.voice.stt.device == "cpu"
    # not spawned in bootstrap → alive is False until _lifespan starts it
    assert m.voice.stt.alive is False
