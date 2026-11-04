"""The model catalog behind ``GET /models`` (RFC-0013 §1-§3, §11).

Read-only: lists installed Ollama models and configured routes with their
profiles and fit. Ollama being down never fails the view -- it is reported
in ``OllamaStatus`` and the configured routes are still listed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from zygos.config.schema import ZygosConfig
from zygos.hardware.probe import HardwareProbe, HardwareSnapshot
from zygos.models.build import apply_running, profile_from_ollama, refresh_from_ollama
from zygos.models.fit import KOKORO_CUDA_RESERVE_BYTES, Fit, VramContext, describe, fit
from zygos.models.profile import ModelProfile, Sourced, resolve
from zygos.models.store import ProfileStore
from zygos.providers.base import Provider
from zygos.providers.types import OllamaModel, OllamaRunning, OllamaShow
from zygos.runtime.context import ExecutionContext
from zygos.runtime.events import ModelFit
from zygos.voice.service import VoiceState

log = logging.getLogger("zygos.models")

# Every generation provider declares Capability.LOCAL_INFERENCE (it is the
# "can generate" contract), so it cannot tell local from cloud. These are the
# built-in providers that run on this machine; anything else is labelled cloud,
# the label that never understates where data goes.
LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "vllm", "fake"})

_ERROR_CHARS = 200


class ModelEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    name: str
    location: Literal["local", "cloud"]
    family: str | None
    parameter_size: str | None
    quantization: str | None
    specialty: tuple[str, ...]
    capabilities: dict[str, bool]
    download_size_bytes: int | None
    loaded: bool
    vram_bytes: int | None
    fit: Fit | None
    fit_text: str | None
    primary: bool
    fallback: bool
    profile_error: str | None
    fields: dict[str, Sourced]


class OllamaStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    configured: bool
    reachable: bool
    error: str | None


class ModelsView(BaseModel):
    model_config = ConfigDict(frozen=True)

    hardware: HardwareSnapshot | None
    ollama: OllamaStatus
    models: tuple[ModelEntry, ...]


def _ollama_name(model: str) -> str:
    return model if ":" in model else f"{model}:latest"


def _value(profile: ModelProfile, key: str) -> Any:
    s = resolve(profile, key)
    return None if s is None else s.value


def _str(profile: ModelProfile, key: str) -> str | None:
    v = _value(profile, key)
    return v if isinstance(v, str) else None


class ModelCatalog:
    def __init__(
        self,
        *,
        providers: Mapping[str, Provider],
        profiles: ProfileStore,
        hardware: HardwareProbe,
        config: ZygosConfig,
        voice_snapshot: Callable[[], VoiceState | None],
        clock: Callable[[], datetime],
    ) -> None:
        self._providers = providers
        self._profiles = profiles
        self._hardware = hardware
        self._config = config
        self._voice_snapshot = voice_snapshot
        self._clock = clock
        # Routes whose profile save was tried and refused (e.g. a filename
        # collision): not retried, so the warning is logged once.
        self._save_tried: set[tuple[str, str]] = set()
        # (provider, name) -> why its profile could not be written (OSError).
        # Persistence never fails the view; the entry carries the reason.
        self._save_errors: dict[tuple[str, str], str] = {}
        # digest -> name of a profile created while /api/show failed. Such a
        # profile is saved with ``digest=None`` so every later view (and a
        # restart) retries show; an alias seen meanwhile joins it.
        self._unshown: dict[str, str] = {}

    # -- routes ---------------------------------------------------------------

    def _route_keys(self) -> tuple[tuple[str, str], set[tuple[str, str]]]:
        def key(provider: str, model: str) -> tuple[str, str]:
            return provider, _ollama_name(model) if provider == "ollama" else model

        p = self._config.providers
        return key(p.primary.provider, p.primary.model), {key(r.provider, r.model) for r in p.fallbacks}

    def _is_local(self, provider: str) -> bool:
        return provider in LOCAL_PROVIDERS

    # -- persistence ----------------------------------------------------------

    def _persisted(self, provider: str, names: list[str], write: Callable[[], Any]) -> bool:
        """Run a profile write; an OSError is logged and recorded, never raised."""
        try:
            write()
        except OSError as exc:
            reason = (str(exc) or type(exc).__name__)[:_ERROR_CHARS]
            log.warning("profile for %s/%s can't be saved: %s", provider, ", ".join(names), reason)
            for n in names:
                self._save_errors[(provider, n)] = reason
            return False
        for n in names:
            self._save_errors.pop((provider, n), None)
        return True

    # -- view -----------------------------------------------------------------

    async def view(self, ctx: ExecutionContext) -> ModelsView:
        hardware = await asyncio.to_thread(self._hardware.scan)
        entries: list[ModelEntry] = []
        ollama = self._providers.get("ollama")
        if ollama is None:
            status = OllamaStatus(configured=False, reachable=False, error=None)
        else:
            tags, running, error = await self._read_ollama(ollama)
            if error is not None:
                status = OllamaStatus(configured=True, reachable=False, error=error)
            else:
                status = OllamaStatus(configured=True, reachable=True, error=None)
                entries.extend(await self._ollama_entries(ctx, ollama, tags, running, hardware))
        installed = {e.name for e in entries}
        entries.extend(self._route_entries(installed, ollama_reachable=status.reachable))
        entries.sort(key=lambda e: (e.location == "cloud", e.family is None, e.family or "", e.name))
        return ModelsView(hardware=hardware, ollama=status, models=tuple(entries))

    async def _read_ollama(
        self, ollama: Any
    ) -> tuple[tuple[OllamaModel, ...], tuple[OllamaRunning, ...], str | None]:
        results = await asyncio.gather(ollama.list_models(), ollama.running_models(),
                                       return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result  # CancelledError and friends propagate
                return (), (), (str(result) or type(result).__name__)[:_ERROR_CHARS]
        tags, running = results
        return tags, running, None

    async def _show(self, ollama: Any, name: str) -> OllamaShow | None:
        try:
            return await ollama.show(name)
        except Exception as exc:  # noqa: BLE001 - a failed show means "build from tags"
            log.info("ollama show %s failed: %s", name, exc)
            return None

    def _add_name(self, profile: ModelProfile, name: str) -> ModelProfile:
        joined = profile if name in profile.names else profile.model_copy(
            update={"names": [*profile.names, name]})
        added: list[ModelProfile] = []
        if self._persisted("ollama", joined.names, lambda: added.append(self._profiles.add_name(profile, name))):
            return added[0]
        return joined

    async def _sync_profile(self, ollama: Any, model: OllamaModel) -> ModelProfile:
        store = self._profiles
        profile = store.get("ollama", model.name)
        if profile is not None and profile.digest is None:
            # Created while show failed: retry it until it answers.
            show = await self._show(ollama, model.name)
            if show is not None:
                return refresh_from_ollama(profile, model, show, at=self._clock())
            return profile
        if profile is not None and profile.digest != model.digest:
            other = store.find_by_digest("ollama", model.digest)
            if len(profile.names) > 1 or other is not None:
                # The name moved to a different model: it leaves this profile
                # (which stays with its other names, or as an orphan keeping
                # its user notes) and joins or starts the profile for its digest.
                self._persisted("ollama", [model.name], lambda: store.remove_name(profile, model.name))
                profile = None
            else:
                show = await self._show(ollama, model.name)
                if show is not None:
                    return refresh_from_ollama(profile, model, show, at=self._clock())
                # Keep the stored values (and digest) so the next view retries show.
                return profile
        if profile is None:
            shared = store.find_by_digest("ollama", model.digest) or self._unshown_profile(model.digest)
            if shared is not None:
                return self._add_name(shared, model.name)
            show = await self._show(ollama, model.name)
            created = profile_from_ollama(model, show, at=self._clock())
            if show is None:
                self._unshown[model.digest] = model.name
                created = created.model_copy(update={"digest": None})
            return created
        return profile

    def _unshown_profile(self, digest: str) -> ModelProfile | None:
        name = self._unshown.get(digest)
        profile = None if name is None else self._profiles.get("ollama", name)
        return profile if profile is not None and profile.digest is None else None

    def _reserve_bytes(self) -> int:
        voice = self._config.voice
        if not (voice.enabled and voice.tts.engine == "kokoro" and voice.tts.device == "cuda"):
            return 0
        snap = self._voice_snapshot()
        tts = snap.tts if snap is not None else None
        if tts is not None and tts.alive and tts.device == "cuda":
            return 0  # already running: its VRAM is out of the free figure
        return KOKORO_CUDA_RESERVE_BYTES

    async def _ollama_entries(
        self,
        ctx: ExecutionContext,
        ollama: Any,
        tags: tuple[OllamaModel, ...],
        running: tuple[OllamaRunning, ...],
        hardware: HardwareSnapshot,
    ) -> list[ModelEntry]:
        primary, fallbacks = self._route_keys()
        reserve = self._reserve_bytes()
        entries: list[ModelEntry] = []
        for model in tags:
            before = self._profiles.get("ollama", model.name)
            profile = await self._sync_profile(ollama, model)
            names = {model.name, *profile.names}
            mine = [r for r in running if r.name in names or r.digest == model.digest]
            loaded = mine[0] if mine else None
            if loaded is not None:
                profile = apply_running(profile, loaded, at=self._clock())
            saved = profile == before or self._persisted(
                "ollama", list({model.name, *profile.names}), lambda: self._profiles.save(profile))
            stored = self._profiles.get("ollama", model.name)
            if saved and stored is not None and stored.digest == profile.digest:
                profile = stored  # what is on disk, user section included
            others = sum(r.size_vram for r in running if r not in mine)
            vram = VramContext(reclaimable_bytes=others, reserve_bytes=reserve)
            fitted = fit(profile, hardware, vram, loaded=loaded is not None)
            await ctx.emit(ModelFit(provider="ollama", model=model.name, level=fitted.level,
                                    needs_bytes=fitted.needs.total_bytes,
                                    free_bytes=fitted.vram_available_bytes,
                                    measured=fitted.needs.measured), source="models")
            entries.append(self._entry(
                profile, provider="ollama", name=model.name, location="local",
                loaded=loaded is not None, vram_bytes=loaded.size_vram if loaded else None,
                fitted=fitted, fit_text=describe(fitted),
                primary=("ollama", model.name) == primary, fallback=("ollama", model.name) in fallbacks))
        return entries

    def _route_entries(self, installed: set[str], *, ollama_reachable: bool) -> list[ModelEntry]:
        """Configured routes not already listed: non-Ollama routes, and Ollama
        routes missing from ``/api/tags`` (not installed, or Ollama is down)."""
        primary, fallbacks = self._route_keys()
        p = self._config.providers
        entries: list[ModelEntry] = []
        seen: set[tuple[str, str]] = set()
        for route in [p.primary, *p.fallbacks]:
            if route.provider == "ollama":
                name = _ollama_name(route.model)
                key = ("ollama", name)
                if name in installed or key in seen:
                    continue
                seen.add(key)
                # Never create a profile for a model that is not there.
                profile = self._profiles.get("ollama", name) or ModelProfile(
                    provider="ollama", model=name, names=[name])
                entries.append(self._entry(
                    profile, provider="ollama", name=name, location="local", loaded=False,
                    vram_bytes=None, fitted=None,
                    fit_text="not installed" if ollama_reachable else "Ollama unreachable",
                    primary=key == primary, fallback=key in fallbacks))
                continue
            key = (route.provider, route.model)
            if key in seen:
                continue
            seen.add(key)
            profile = self._profiles.get(route.provider, route.model)
            if profile is None:
                profile = ModelProfile(provider=route.provider, model=route.model, names=[route.model])
                if key not in self._save_tried and self._profiles.error_for(*key) is None:
                    self._save_tried.add(key)  # once; a refused save is not retried
                    new = profile
                    if self._persisted(route.provider, [route.model], lambda: self._profiles.save(new)):
                        profile = self._profiles.get(route.provider, route.model) or profile
                    else:
                        self._save_tried.discard(key)  # an OSError may clear up: retry next view
            local = self._is_local(route.provider)
            entries.append(self._entry(
                profile, provider=route.provider, name=route.model,
                location="local" if local else "cloud", loaded=False, vram_bytes=None, fitted=None,
                fit_text=f"fit not checked for {route.provider}" if local else "fit doesn't apply (cloud)",
                primary=key == primary, fallback=key in fallbacks))
        return entries

    def _entry(self, profile: ModelProfile, *, provider: str, name: str, location: Literal["local", "cloud"],
               loaded: bool, vram_bytes: int | None, fitted: Fit | None, fit_text: str | None,
               primary: bool, fallback: bool) -> ModelEntry:
        keys = sorted({*profile.values, *profile.user})
        fields = {k: s for k in keys if (s := resolve(profile, k)) is not None}
        specialty = _value(profile, "identity.specialty")
        size = _value(profile, "identity.download_size_bytes")
        error = self._profiles.error_for(provider, name)
        save_error = self._save_errors.get((provider, name))
        if error is not None:
            profile_error: str | None = f"profile file can't be read: {error.reason[:_ERROR_CHARS]}"
        elif save_error is not None:
            profile_error = f"profile can't be saved: {save_error}"
        else:
            profile_error = None
        return ModelEntry(
            provider=provider, name=name, location=location,
            family=_str(profile, "identity.family"),
            parameter_size=_str(profile, "identity.parameter_size"),
            quantization=_str(profile, "identity.quantization"),
            specialty=tuple(s for s in specialty if isinstance(s, str)) if isinstance(specialty, list) else (),
            capabilities={k.removeprefix("capabilities."): s.value for k, s in fields.items()
                          if k.startswith("capabilities.") and isinstance(s.value, bool)},
            download_size_bytes=size if isinstance(size, int) and not isinstance(size, bool) else None,
            loaded=loaded, vram_bytes=vram_bytes, fit=fitted, fit_text=fit_text,
            primary=primary, fallback=fallback,
            profile_error=profile_error,
            fields=fields)
