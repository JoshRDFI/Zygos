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


def test_doctor_does_not_probe_ollama(tmp_path):
    import asyncio
    from dataclasses import replace

    import httpx

    from zygos.backends.settings import BackendsSettings, LlamaCppBackend
    from zygos.backends.store import SqliteBackendsStore
    from zygos.cli.doctor import run_doctor
    from zygos.runtime.bootstrap import build_runtime

    config = tmp_path / "config.yaml"
    db = tmp_path / "p.db"
    config.write_text(f"personalization:\n  db_path: '{db}'\n"
                      "providers:\n  primary: {provider: fake, model: fake-1}\n")
    SqliteBackendsStore(db).set(BackendsSettings(
        llamacpp=LlamaCppBackend(models_dir=str(tmp_path))))
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(500)

    async def go():
        runtime = build_runtime(config)
        probe_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_doctor(replace(runtime, http_client=probe_client),
                                    gpu_query=lambda: None)
        finally:
            await probe_client.aclose()
            await runtime.aclose()

    report = asyncio.run(go())
    assert calls == []
    assert any(c.name == "llamacpp_models" for c in report.checks)


def test_doctor_backends_restart_warns(tmp_path):
    from dataclasses import replace  # noqa: F401
    import asyncio

    from zygos.backends.settings import BackendsSettings, OllamaBackend
    from zygos.backends.store import SqliteBackendsStore
    from zygos.cli.doctor import run_doctor
    from zygos.runtime.bootstrap import build_runtime

    config = tmp_path / "config.yaml"
    db = tmp_path / "p.db"
    config.write_text(f"personalization:\n  db_path: '{db}'\n"
                      "providers:\n  primary: {provider: fake, model: fake-1}\n")
    store = SqliteBackendsStore(db)

    async def go():
        runtime = build_runtime(config)  # started with no record
        store.set(BackendsSettings(ollama=OllamaBackend(base_url="http://new:1")))
        try:
            return await run_doctor(runtime, gpu_query=lambda: None)
        finally:
            await runtime.aclose()

    by = {c.name: c for c in asyncio.run(go()).checks}
    assert by["backends_restart"].warn and by["backends_restart"].ok
    assert by["ollama_address"].detail.startswith("http://new:1")


def test_doctor_shows_config_only_ollama_address(tmp_path):
    import asyncio

    from zygos.cli.doctor import run_doctor
    from zygos.runtime.bootstrap import build_runtime

    config = tmp_path / "config.yaml"
    config.write_text(
        f"personalization:\n  db_path: '{tmp_path / 'p.db'}'\n"
        "providers:\n  primary: {provider: ollama, model: q}\n"
        "  credentials:\n    ollama: {base_url: 'http://cfg:1'}\n"
    )

    async def go():
        runtime = build_runtime(config)
        try:
            return await run_doctor(runtime, gpu_query=lambda: None)
        finally:
            await runtime.aclose()

    by = {c.name: c for c in asyncio.run(go()).checks}
    assert by["ollama_address"].detail == "http://cfg:1 (from config)"
    assert "backends_restart" not in by


class _ListingOllama:
    name = "ollama"
    capabilities = frozenset()

    def __init__(self, names):
        self._names = names

    async def list_models(self):
        from zygos.providers.types import OllamaModel

        return tuple(OllamaModel(name=n, size=1024**3, digest=f"d-{n}", family="x") for n in self._names)

    async def running_models(self):
        return ()

    async def show(self, model):
        from zygos.errors import ProviderUnavailable

        raise ProviderUnavailable("no show", provider="ollama")


def _default_check(tmp_path, saved, installed=None):
    import asyncio

    from zygos.cli.doctor import run_doctor
    from zygos.models.choices import DefaultModel, ModelChoices, SqliteModelChoicesStore
    from zygos.runtime.bootstrap import build_runtime

    config = tmp_path / "config.yaml"
    db = tmp_path / "p.db"
    config.write_text(
        f"personalization:\n  db_path: '{db}'\n"
        "providers:\n  primary: {provider: ollama, model: 'qwen3:8b'}\n"
    )
    if saved is not None:
        SqliteModelChoicesStore(db).set(ModelChoices(default_model=DefaultModel(provider=saved[0], model=saved[1])))

    async def go():
        runtime = build_runtime(config)
        try:
            if installed is not None:
                # Known installation: the catalog listed Ollama in this process
                # (as the server does on GET /models), through a fake Ollama.
                runtime.model_catalog._providers["ollama"] = _ListingOllama(installed)
                await runtime.model_catalog.view(runtime.new_context())
            report = await run_doctor(runtime, gpu_query=lambda: None)
            return next(c for c in report.checks if c.name == "default_model")
        finally:
            await runtime.aclose()

    return asyncio.run(go())


def test_doctor_default_model_config(tmp_path):
    check = _default_check(tmp_path, None)
    assert check.ok and not check.warn
    assert check.detail == "ollama/qwen3:8b (config)"


def test_doctor_default_model_saved(tmp_path):
    check = _default_check(tmp_path, ("ollama", "gemma4:e4b"), installed={"gemma4:e4b"})
    assert check.ok and not check.warn
    assert check.detail == "ollama/gemma4:e4b (saved)"


def test_doctor_default_model_saved_installation_unknown_is_not_an_all_clear(tmp_path):
    """Final fix wave I4: the doctor's own process has never listed Ollama, so it
    can't know a saved default was deleted -- it says so instead of '(saved)'."""
    check = _default_check(tmp_path, ("ollama", "gone:7b"))
    assert check.ok and not check.warn
    assert check.detail == ("ollama/gone:7b (saved; installation not checked — "
                            "run with the server or use --probe)")


def test_doctor_default_model_saved_but_ignored_warns(tmp_path):
    check = _default_check(tmp_path, ("ollama", "gone:7b"), installed={"qwen3:8b"})
    assert check.ok and check.warn
    assert check.detail == ("saved default ollama/gone:7b ignored: not installed; "
                            "using ollama/qwen3:8b")


def test_doctor_probe_names_the_model_that_answered(tmp_path):
    """Final fix wave minor (d): --probe generates through the saved default, so
    it says which model it probed rather than 'primary route responded'."""
    import asyncio

    from zygos.cli.doctor import run_doctor
    from zygos.models.choices import DefaultModel, ModelChoices, SqliteModelChoicesStore
    from zygos.runtime.bootstrap import build_runtime

    config = tmp_path / "config.yaml"
    db = tmp_path / "p.db"
    config.write_text(f"personalization:\n  db_path: '{db}'\n"
                      "providers:\n  primary: {provider: fake, model: fake-1}\n")

    async def go():
        runtime = build_runtime(config)
        try:
            report = await run_doctor(runtime, probe=True, gpu_query=lambda: None)
            return next(c for c in report.checks if c.name == "probe")
        finally:
            await runtime.aclose()

    first = asyncio.run(go())
    assert first.ok and first.detail == "fake/fake-1 responded"
    SqliteModelChoicesStore(db).set(ModelChoices(default_model=DefaultModel(provider="fake", model="saved-1")))
    second = asyncio.run(go())
    assert second.ok and second.detail == "fake/saved-1 responded (the saved default)"
