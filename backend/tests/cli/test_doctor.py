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


def _doctor_report(tmp_path, backends):
    import asyncio

    from zygos.backends.store import SqliteBackendsStore
    from zygos.cli.doctor import run_doctor
    from zygos.runtime.bootstrap import build_runtime

    config = tmp_path / "config.yaml"
    db = tmp_path / "p.db"
    config.write_text(
        f"personalization:\n  db_path: '{db}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n"
    )
    if backends is not None:
        SqliteBackendsStore(db).set(backends)

    async def go():
        runtime = build_runtime(config)
        try:
            return await run_doctor(runtime, gpu_query=lambda: None)
        finally:
            await runtime.aclose()

    return asyncio.run(go())


def test_doctor_no_backends_adds_no_checks(tmp_path):
    report = _doctor_report(tmp_path, None)
    names = {c.name for c in report.checks}
    assert not names & {"ollama_address", "llamacpp_server", "llamacpp_models", "vllm",
                        "backends_restart"}


def test_doctor_broken_llamacpp_warns_and_report_stays_ok(tmp_path):
    from zygos.backends.settings import BackendsSettings, LlamaCppBackend

    report = _doctor_report(tmp_path, BackendsSettings(
        llamacpp=LlamaCppBackend(server_path=str(tmp_path / "nope"),
                                 models_dir=str(tmp_path / "nofolder"))))
    by = {c.name: c for c in report.checks}
    assert by["llamacpp_server"].warn and by["llamacpp_server"].ok
    assert by["llamacpp_models"].warn and by["llamacpp_models"].ok
    assert report.ok


def test_doctor_ollama_address_and_vllm_down(tmp_path):
    from zygos.backends.settings import BackendsSettings, OllamaBackend, VllmEndpoint

    report = _doctor_report(tmp_path, BackendsSettings(
        ollama=OllamaBackend(base_url="http://o:1"),
        vllm=[VllmEndpoint(base_url="http://127.0.0.1:1/v1")]))
    by = {c.name: c for c in report.checks}
    assert by["ollama_address"].detail == "http://o:1 (from backends)"
    assert by["vllm"].warn and report.ok
    assert "backends_restart" not in by
