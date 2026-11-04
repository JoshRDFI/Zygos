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

    # -- routes ---------------------------------------------------------------

    def _route_keys(self) -> tuple[tuple[str, str], set[tuple[str, str]]]:
        def key(provider: str, model: str) -> tuple[str, str]:
            return provider, _ollama_name(model) if provider == "ollama" else model

        p = self._config.providers
        return key(p.primary.provider, p.primary.model), {key(r.provider, r.model) for r in p.fallbacks}

    def _is_local(self, provider: str) -> bool:
        return provider in LOCAL_PROVIDERS

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
        entries.extend(self._route_entries())
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

    async def _sync_profile(self, ollama: Any, model: OllamaModel) -> ModelProfile:
        store = self._profiles
        profile = store.get("ollama", model.name)
        if profile is not None and profile.digest != model.digest:
            other = store.find_by_digest("ollama", model.digest)
            if len(profile.names) > 1 or other is not None:
                # The name moved to a different model: it leaves this profile
                # (which stays with its other names, or as an orphan keeping
                # its user notes) and joins or starts the profile for its digest.
                store.remove_name(profile, model.name)
                profile = None
            else:
                show = await self._show(ollama, model.name)
                if show is not None:
                    return refresh_from_ollama(profile, model, show, at=self._clock())
                # Keep the stored values (and digest) so the next view retries show.
                return profile
        if profile is None:
            shared = store.find_by_digest("ollama", model.digest)
            if shared is not None:
                return store.add_name(shared, model.name)
            show = await self._show(ollama, model.name)
            return profile_from_ollama(model, show, at=self._clock())
        return profile

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
            if profile != before:
                self._profiles.save(profile)
            stored = self._profiles.get("ollama", model.name)
            if stored is not None and stored.digest == profile.digest:
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

    def _route_entries(self) -> list[ModelEntry]:
        primary, fallbacks = self._route_keys()
        p = self._config.providers
        entries: list[ModelEntry] = []
        seen: set[tuple[str, str]] = set()
        for route in [p.primary, *p.fallbacks]:
            key = (route.provider, route.model)
            if route.provider == "ollama" or key in seen:
                continue
            seen.add(key)
            profile = self._profiles.get(route.provider, route.model)
            if profile is None:
                profile = ModelProfile(provider=route.provider, model=route.model, names=[route.model])
                if key not in self._save_tried and self._profiles.error_for(*key) is None:
                    self._save_tried.add(key)
                    self._profiles.save(profile)  # once; a refused save is not retried
                    profile = self._profiles.get(route.provider, route.model) or profile
            local = self._is_local(route.provider)
            entries.append(self._entry(
                profile, provider=route.provider, name=route.model,
                location="local" if local else "cloud", loaded=False, vram_bytes=None, fitted=None,
                fit_text=f"fit not checked for {route.provider}" if local else None,
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
            profile_error=error.reason[:_ERROR_CHARS] if error is not None else None,
            fields=fields)
