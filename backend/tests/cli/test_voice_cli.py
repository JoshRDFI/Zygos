from zygos.cli import __main__ as cli


def test_voice_setup_gpu_dispatches_with_force(monkeypatch):
    seen = {}

    def fake_setup_gpu(*, force=False, **_):
        seen["force"] = force
        return 0

    monkeypatch.setattr("zygos.voice.gpu_setup.setup_gpu", fake_setup_gpu)
    assert cli.main(["voice", "setup-gpu", "--force"]) == 0
    assert seen == {"force": True}


def test_voice_setup_gpu_propagates_failure(monkeypatch):
    monkeypatch.setattr("zygos.voice.gpu_setup.setup_gpu", lambda **_: 3)
    assert cli.main(["voice", "setup-gpu"]) == 3
