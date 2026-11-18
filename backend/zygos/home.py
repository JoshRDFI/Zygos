"""Where Zygos keeps its data: one root for every relative ``.zygos/...`` path.

Stability: Experimental.

Root order: ``ZYGOS_HOME`` (set and non-empty) -> the checkout's ``backend/``
folder (when it holds Zygos's own ``pyproject.toml``) -> a per-user data folder.
Finding the root never creates anything. Stdlib only.
"""

from __future__ import annotations

import os
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

SOURCE_ENV = "ZYGOS_HOME"
SOURCE_CHECKOUT = "checkout"
SOURCE_USER = "user data folder"


@dataclass(frozen=True)
class ZygosHome:
    root: Path
    source: str


def _expand(value: str, home: Path, cwd: Path) -> Path:
    if value == "~" or value.startswith(("~/", "~\\")):
        return home / value[2:] if len(value) > 1 else home
    p = Path(value)
    return p if p.is_absolute() else cwd / p


def _is_checkout(package_dir: Path) -> bool:
    try:
        with open(package_dir / "pyproject.toml", "rb") as fh:
            data = tomllib.load(fh)
        return data["project"]["name"] == "zygos"
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError):
        return False


def _user_folder(environ: Mapping[str, str], platform: str, home: Path) -> Path:
    if platform == "win32":
        local = environ.get("LOCALAPPDATA")
        return (Path(local) if local else home / "AppData" / "Local") / "zygos"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "zygos"
    xdg = environ.get("XDG_DATA_HOME")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / "zygos"
    return home / ".local" / "share" / "zygos"


def find_zygos_home(
    *,
    environ: Mapping[str, str],
    package_dir: Path,
    platform: str,
    home: Path,
    cwd: Path,
) -> ZygosHome:
    env = environ.get(SOURCE_ENV)
    if env:
        return ZygosHome(_expand(env, home, cwd), SOURCE_ENV)
    if _is_checkout(package_dir):
        return ZygosHome(package_dir, SOURCE_CHECKOUT)
    return ZygosHome(_user_folder(environ, platform, home), SOURCE_USER)


_cached: ZygosHome | None = None


def zygos_home() -> ZygosHome:
    global _cached
    if _cached is None:
        import zygos

        _cached = find_zygos_home(
            environ=os.environ,
            package_dir=Path(zygos.__file__).resolve().parents[1],
            platform=sys.platform,
            home=Path.home(),
            cwd=Path.cwd(),
        )
    return _cached


def reset_zygos_home_cache() -> None:
    global _cached
    _cached = None


def resolve_path(value: str) -> str:
    """Absolute stays; ``~`` expands; anything else is relative to the root."""
    if value == "~" or value.startswith(("~/", "~\\")):
        return str(_expand(value, Path.home(), Path.cwd()))
    p = Path(value)
    if p.is_absolute():
        return value
    return str(zygos_home().root / p)


def stray_data_dir(cwd: Path | None = None) -> Path | None:
    """The unused ``<cwd>/.zygos`` folder, or None when absent or the real one."""
    stray = (cwd or Path.cwd()) / ".zygos"
    if not stray.is_dir():
        return None
    if stray.resolve() == (zygos_home().root / ".zygos").resolve():
        return None
    return stray


def stray_message(stray: Path) -> str:
    start = stray.parent
    root = zygos_home().root
    return (
        f"a .zygos folder in {start} is not used; Zygos data is in {root}/.zygos "
        f"(set ZYGOS_HOME={start} to use it instead)"
    )
