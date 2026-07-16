from pathlib import Path

from zygos.voice.kokoro_assets import MODEL, VOICES, resolve_paths


def test_resolve_paths_defaults_and_override():
    onnx_d, voices_d = resolve_paths(None)
    assert onnx_d == Path(".zygos/models/kokoro") / MODEL.filename
    assert voices_d == Path(".zygos/models/kokoro") / VOICES.filename

    onnx_o, voices_o = resolve_paths("/tmp/models")
    assert onnx_o == Path("/tmp/models") / MODEL.filename
    assert voices_o == Path("/tmp/models") / VOICES.filename
