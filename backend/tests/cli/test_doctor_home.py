import asyncio
import logging

from zygos.cli.__main__ import main
from zygos.home import stray_message


def _cfg(tmp_path, extra=""):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"memory:\n  db_path: '{tmp_path / 'm.db'}'\n"
        f"personalization:\n  db_path: '{tmp_path / 'p.db'}'\n"
        f"tools:\n  workspace_root: '{tmp_path / 'ws'}'\n"
        f"models:\n  profiles_dir: '{tmp_path / 'profiles'}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n" + extra
    )
    return cfg


def _report(tmp_path):
    from zygos.cli.doctor import run_doctor
    from zygos.runtime.bootstrap import build_runtime

    cfg = _cfg(tmp_path)

    async def go():
        runtime = build_runtime(cfg)
        try:
            return await run_doctor(runtime, gpu_query=lambda: None)
        finally:
            await runtime.aclose()

    return asyncio.run(go())


def _by(report):
    return {c.name: c for c in report.checks}


def test_doctor_shows_root(tmp_path):
    from zygos.home import zygos_home

    root = zygos_home().root
    check = _by(_report(tmp_path))["zygos_home"]
    assert check.ok and not check.warn
    assert check.detail == f"{root} (ZYGOS_HOME)"


def test_stray_folder_warns(tmp_path, monkeypatch):
    from zygos.home import zygos_home

    root = zygos_home().root
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / ".zygos").mkdir(parents=True)
    monkeypatch.chdir(elsewhere)
    report = _report(tmp_path)
    check = _by(report)["stray_data_folder"]
    assert check.warn and check.ok
    assert check.detail == stray_message(elsewhere / ".zygos")
    assert check.detail == (
        f"a .zygos folder in {elsewhere} is not used; Zygos data is in {root}/.zygos "
        f"(set ZYGOS_HOME={elsewhere} to use it instead)"
    )
    assert report.ok


def test_no_stray_warning_from_root_or_plain_subfolder(tmp_path, monkeypatch):
    from zygos.home import zygos_home

    root = zygos_home().root
    (root / ".zygos").mkdir(parents=True)
    (root / "sub").mkdir()
    link = tmp_path / "link"
    link.symlink_to(root)
    for where in (root, root / "sub", link):
        monkeypatch.chdir(where)
        checks = _by(_report(tmp_path))
        assert "zygos_home" in checks  # positive anchor: doctor really ran
        assert "stray_data_folder" not in checks


def test_doctor_creates_no_root(tmp_path, monkeypatch):
    from zygos.cli.doctor import run_doctor
    from zygos.home import reset_zygos_home_cache
    from zygos.runtime.bootstrap import build_runtime

    fresh = tmp_path / "fresh"
    monkeypatch.setenv("ZYGOS_HOME", str(fresh))
    reset_zygos_home_cache()
    cfg = tmp_path / "config.yaml"  # default (.zygos/...) paths, fake provider only
    cfg.write_text("providers:\n  primary: {provider: fake, model: fake-1}\n")

    async def go():
        runtime = build_runtime(cfg)
        try:
            return await run_doctor(runtime, gpu_query=lambda: None)
        finally:
            await runtime.aclose()

    report = asyncio.run(go())
    assert _by(report)["zygos_home"].detail == f"{fresh} (ZYGOS_HOME)"
    assert not fresh.exists()


def test_doctor_survives_unsearchable_start_folder(tmp_path, monkeypatch):
    locked = tmp_path / "locked"
    locked.mkdir()
    monkeypatch.chdir(locked)
    locked.chmod(0)
    try:
        checks = _by(_report(tmp_path))
    finally:
        locked.chmod(0o700)
    assert "zygos_home" in checks and "stray_data_folder" not in checks


def test_serve_logs_stray_warning(tmp_path, monkeypatch, caplog):
    import zygos.api.app as app
    from zygos.home import zygos_home

    monkeypatch.setattr(app, "run_server", lambda *a, **k: None)
    cfg = _cfg(tmp_path)
    caplog.set_level(logging.WARNING, logger="zygos.home")

    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert main(["--config", str(cfg), "serve"]) == 0
    assert not [r for r in caplog.records if r.name == "zygos.home"]

    elsewhere = tmp_path / "elsewhere"
    (elsewhere / ".zygos").mkdir(parents=True)
    monkeypatch.chdir(elsewhere)
    assert main(["--config", str(cfg), "serve"]) == 0
    records = [r for r in caplog.records if r.name == "zygos.home"]
    assert len(records) == 1
    assert records[0].getMessage() == stray_message(elsewhere / ".zygos")
    assert str(zygos_home().root) in records[0].getMessage()
