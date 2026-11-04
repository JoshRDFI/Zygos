"""Recursive GGUF model-folder scan (RFC-0014 §3). Lists files only; no reads."""

from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import BaseModel

_SPLIT = re.compile(r"-\d{5}-of-\d{5}$")


class GgufModel(BaseModel):
    name: str
    files: tuple[Path, ...]
    mmproj: Path | None = None
    mmproj_ambiguous: tuple[Path, ...] = ()
    size_bytes: int


def _gguf_files(root: Path) -> list[Path]:
    found: list[Path] = []
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file() and e.name.lower().endswith(".gguf"):
                            found.append(Path(e.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def scan_folder(root: Path) -> list[GgufModel]:
    by_dir: dict[Path, tuple[list[Path], list[Path]]] = {}
    for f in _gguf_files(root):
        models, projs = by_dir.setdefault(f.parent, ([], []))
        (projs if "mmproj" in f.name.lower() else models).append(f)

    out: list[GgufModel] = []
    for directory, (models, projs) in by_dir.items():
        groups: dict[str, list[Path]] = {}
        for f in sorted(models):
            stem = _SPLIT.sub("", f.name[: -len(".gguf")])
            groups.setdefault(stem, []).append(f)
        paired = projs[0] if len(groups) == 1 and len(projs) == 1 else None
        ambiguous = () if paired or not groups else tuple(sorted(projs))
        for stem, files in groups.items():
            try:
                rel = (directory / stem).relative_to(root)
            except ValueError:
                rel = Path(stem)
            out.append(
                GgufModel(
                    name=rel.as_posix(),
                    files=tuple(files),
                    mmproj=paired,
                    mmproj_ambiguous=ambiguous,
                    size_bytes=sum(_size(p) for p in files),
                )
            )
    return sorted(out, key=lambda m: m.name)
