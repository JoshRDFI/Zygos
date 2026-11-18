from pathlib import Path

import pytest

import zygos
from zygos.home import (
    ZygosHome,
    find_zygos_home,
    reset_zygos_home_cache,
    resolve_path,
    zygos_home,
)

from conftest import _suite_home_env

CHECKOUT_TOML = '[project]\nname = "zygos"\n'


def _checkout(tmp_path: Path) -> Path:
    d = tmp_path / "ck"
    d.mkdir()
    (d / "pyproject.toml").write_text(CHECKOUT_TOML)
    return d


def _find(tmp_path, environ=None, package_dir=None, platform="linux", home=None, cwd=None):
    return find_zygos_home(
        environ=environ or {},
        package_dir=package_dir or tmp_path / "nopkg",
        platform=platform,
        home=home or tmp_path / "home",
        cwd=cwd or tmp_path / "cwd",
    )


def test_env_wins(tmp_path):
    r = _find(tmp_path, {"ZYGOS_HOME": str(tmp_path / "h")}, package_dir=_checkout(tmp_path))
    assert r == ZygosHome(root=tmp_path / "h", source="ZYGOS_HOME")


def test_empty_env_is_unset(tmp_path):
    r = _find(tmp_path, {"ZYGOS_HOME": ""}, package_dir=_checkout(tmp_path))
    assert r.source == "checkout"


def test_relative_and_tilde_env(tmp_path):
    assert _find(tmp_path, {"ZYGOS_HOME": "rel"}).root == tmp_path / "cwd" / "rel"
    assert _find(tmp_path, {"ZYGOS_HOME": "~/z"}).root == tmp_path / "home" / "z"


def test_checkout_detected(tmp_path):
    ck = _checkout(tmp_path)
    r = _find(tmp_path, package_dir=ck)
    assert r.root == ck and r.source == "checkout"


@pytest.mark.parametrize(
    "content",
    [None, "not toml [", '[project]\nname = "other"\n', 'x = 1\n'],
)
def test_not_a_checkout_falls_through(tmp_path, content):
    d = tmp_path / "pk"
    d.mkdir()
    if content is not None:
        (d / "pyproject.toml").write_text(content)
    r = _find(tmp_path, package_dir=d)
    assert r.root == tmp_path / "home" / ".local/share/zygos"
    assert r.source == "user data folder"


def test_user_folder_per_platform(tmp_path):
    home = tmp_path / "home"
    assert _find(tmp_path, {"XDG_DATA_HOME": "/x/data"}).root == Path("/x/data/zygos")
    assert _find(tmp_path, {"XDG_DATA_HOME": "rel"}).root == home / ".local/share/zygos"
    assert _find(tmp_path, platform="darwin").root == home / "Library/Application Support/zygos"
    assert _find(tmp_path, {"LOCALAPPDATA": "C:/L"}, platform="win32").root == Path("C:/L") / "zygos"
    assert _find(tmp_path, platform="win32").root == home / "AppData/Local/zygos"


def test_real_root_is_this_checkout(monkeypatch):
    monkeypatch.delenv("ZYGOS_HOME", raising=False)
    reset_zygos_home_cache()
    r = zygos_home()
    assert r.root == Path(zygos.__file__).resolve().parents[1]
    assert r.source == "checkout"


def test_root_is_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("ZYGOS_HOME", str(tmp_path / "a"))
    reset_zygos_home_cache()
    first = zygos_home()
    assert zygos_home() is first
    monkeypatch.setenv("ZYGOS_HOME", str(tmp_path / "b"))
    assert zygos_home() is first
    reset_zygos_home_cache()
    assert zygos_home().root == tmp_path / "b"


def test_resolve_path(monkeypatch, tmp_path):
    monkeypatch.setenv("ZYGOS_HOME", str(tmp_path))
    reset_zygos_home_cache()
    assert resolve_path(".zygos/a.db") == str(tmp_path / ".zygos/a.db")
    assert resolve_path(str(tmp_path / "x")) == str(tmp_path / "x")
    assert resolve_path("~/q") == str(Path.home() / "q")


def test_finding_root_creates_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("ZYGOS_HOME", str(tmp_path / "nope"))
    reset_zygos_home_cache()
    zygos_home()
    resolve_path(".zygos/a")
    assert not (tmp_path / "nope").exists()


def test_live_markers_use_real_root(tmp_path):
    assert _suite_home_env(markers={"live_voice"}) is None
    assert _suite_home_env(markers={"live_gpu"}) is None
    assert _suite_home_env(markers=set(), tmp=tmp_path) == tmp_path / "zygos-home"
