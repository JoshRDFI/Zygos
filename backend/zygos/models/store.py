"""On-disk profile store. Two hard rules (RFC-0013 §2):

* the ``user`` section is never rewritten from memory - it is re-read from
  disk immediately before every save;
* a file that cannot be parsed is never overwritten.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel

from zygos.models.profile import ModelProfile, safe_filename

log = logging.getLogger("zygos.models")


class ProfileError(BaseModel):
    path: str
    reason: str


class ProfileStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._profiles: dict[Path, ModelProfile] = {}
        self._index: dict[tuple[str, str], Path] = {}
        self._errors: dict[Path, ProfileError] = {}

    def _path_for(self, provider: str, model: str) -> Path:
        return self._root / provider / f"{safe_filename(model)}.json"

    def _index_profile(self, path: Path, profile: ModelProfile) -> None:
        """Index by ``names``. ``model`` names the file only: after a name is
        split off (``remove_name``) the file keeps its ``model`` but no longer
        answers to it. A profile with no names falls back to ``model``, without
        displacing a profile that holds that name."""
        self._profiles[path] = profile
        for n in profile.names:
            self._index[(profile.provider, n)] = path
        if not profile.names:
            self._index.setdefault((profile.provider, profile.model), path)

    def _known_path(self, profile: ModelProfile) -> Path | None:
        for n in profile.names:
            path = self._index.get((profile.provider, n))
            if path is not None:
                return path
        return None

    def _split_path(self, taken: Path) -> Path:
        """A free sibling of ``taken`` for a name split off the profile in it.
        ``~`` never appears in a ``safe_filename``, so this cannot collide with a
        real model's file."""
        n = 2
        while True:
            path = taken.with_name(f"{taken.stem}~{n}.json")
            if not path.exists() and path not in self._profiles and path not in self._errors:
                return path
            n += 1

    def _parse(self, path: Path) -> ModelProfile | None:
        """Parse ``path``; on failure record a ProfileError and return None."""
        try:
            return ModelProfile.model_validate_json(path.read_bytes())
        except Exception as exc:  # malformed JSON, schema mismatch, unreadable
            self._errors[path] = ProfileError(path=str(path), reason=str(exc))
            return None

    def load_all(self) -> None:
        if not self._root.is_dir():
            return
        for pdir in sorted(p for p in self._root.iterdir() if p.is_dir()):
            for path in sorted(pdir.glob("*.json")):
                profile = self._parse(path)
                if profile is not None:
                    self._errors.pop(path, None)
                    self._index_profile(path, profile)

    def get(self, provider: str, name: str) -> ModelProfile | None:
        path = self._index.get((provider, name))
        return self._profiles.get(path) if path else None

    def error_for(self, provider: str, name: str) -> ProfileError | None:
        known = self._index.get((provider, name))
        return self._errors.get(known or self._path_for(provider, name))

    def find_by_digest(self, provider: str, digest: str) -> ModelProfile | None:
        for p in self._profiles.values():
            if p.provider == provider and p.digest == digest:
                return p
        return None

    def save(self, profile: ModelProfile) -> None:
        path = self._known_path(profile) or self._path_for(profile.provider, profile.model)
        if path in self._errors:
            log.warning("refusing to overwrite unparseable profile %s: %s", path, self._errors[path].reason)
            return
        if path.exists():
            on_disk = self._parse(path)
            if on_disk is None:
                log.warning("refusing to overwrite unparseable profile %s: %s", path, self._errors[path].reason)
                return
            if not set(on_disk.names) & set(profile.names):
                if on_disk.model != profile.model:
                    log.warning(
                        "refusing to save %r: %s belongs to a different model (%r)",
                        profile.model, path, on_disk.model,
                    )
                    return
                # This name was split off the profile in that file: give it its own.
                path = self._split_path(path)
            else:
                profile = profile.model_copy(update={"user": on_disk.user})
        self._write(path, profile)

    def _write(self, path: Path, profile: ModelProfile) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        try:
            tmp.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            log.warning("failed to write profile %s: %s", path, exc)
            raise
        self._index_profile(path, profile)

    def add_name(self, profile: ModelProfile, name: str) -> ModelProfile:
        if name not in profile.names:
            profile = profile.model_copy(update={"names": [*profile.names, name]})
        self.save(profile)
        return self.get(profile.provider, name) or profile

    def remove_name(self, profile: ModelProfile, name: str) -> ModelProfile:
        """Detach ``name`` (its Ollama digest moved on). The profile keeps its
        file, even when ``name`` was its ``model``; ``name`` stops resolving to it.
        Returns the profile as saved (unchanged when the file is unparseable)."""
        key = (profile.provider, name)
        path = self._index.get(key)
        if path is None or path in self._errors:
            return profile
        on_disk = self._parse(path)
        if on_disk is None:
            log.warning("refusing to overwrite unparseable profile %s: %s", path, self._errors[path].reason)
            return profile
        current = self._profiles.get(path, profile)
        updated = current.model_copy(update={"names": [n for n in current.names if n != name],
                                             "user": on_disk.user})
        del self._index[key]
        self._write(path, updated)
        return updated
