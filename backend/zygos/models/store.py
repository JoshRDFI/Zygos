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
        self._profiles[path] = profile
        for n in {profile.model, *profile.names}:
            self._index[(profile.provider, n)] = path

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
        path = self._path_for(profile.provider, profile.model)
        if path in self._errors:
            log.warning("refusing to overwrite unparseable profile %s: %s", path, self._errors[path].reason)
            return
        if path.exists():
            on_disk = self._parse(path)
            if on_disk is None:
                log.warning("refusing to overwrite unparseable profile %s: %s", path, self._errors[path].reason)
                return
            profile = profile.model_copy(update={"user": on_disk.user})
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)
        self._index_profile(path, profile)

    def add_name(self, profile: ModelProfile, name: str) -> ModelProfile:
        if name not in profile.names:
            profile = profile.model_copy(update={"names": [*profile.names, name]})
        self.save(profile)
        return self.get(profile.provider, name) or profile
