from zygos.cli.__main__ import main


def test_doctor_passes_on_healthy_local_config():
    code = main(["doctor"])  # default ollama primary: keyless, capabilities bound
    assert code == 0


def test_doctor_fails_when_required_capability_unbound(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "providers:\n"
        "  primary: {provider: ollama, model: qwen3:8b}\n"
        "required_capabilities: [vision]\n"
    )
    code = main(["--config", str(config), "doctor"])
    assert code == 1


def test_doctor_fails_when_primary_missing_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = tmp_path / "config.yaml"
    config.write_text(
        "providers:\n"
        "  primary: {provider: openai, model: gpt-4o}\n"
    )  # no credentials block -> load_config passes -> doctor must catch it
    code = main(["--config", str(config), "doctor"])
    assert code == 1


def test_doctor_probe_pings_primary_offline(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "providers:\n"
        "  primary: {provider: fake, model: fake-1}\n"
    )
    code = main(["--config", str(config), "doctor", "--probe"])
    assert code == 0
