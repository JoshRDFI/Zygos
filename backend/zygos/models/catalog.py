"""The model catalog behind ``GET /models`` (RFC-0013 §1-§3, §11; RFC-0014 §3, §9).

Read-only: lists installed Ollama models, the llama.cpp GGUF folder's models,
the models the vLLM server serves, and configured routes, with their profiles
and fit. A backend being down never fails the view -- Ollama's state is in
``OllamaStatus``, vLLM's in its entry -- and the rest is still listed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Collection, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from zygos.backends.addresses import resolve_address, routed
from zygos.backends.checks import Check, VllmModel, read_vllm
from zygos.backends.launch import LaunchError, parse_launch, read_launch
from zygos.backends.settings import BackendsSettings, LlamaCppBackend, effective_args
from zygos.backends.store import BackendsStore
from zygos.config.schema import ZygosConfig
from zygos.hardware.probe import HardwareProbe, HardwareSnapshot
from zygos.models.build import apply_running, profile_from_ollama, refresh_from_ollama
from zygos.models.build_gguf import LLAMACPP_PROVIDER, gguf_digest, profile_from_gguf
from zygos.models.default import DefaultStatus
from zygos.models.fit import (
    KOKORO_CUDA_RESERVE_BYTES,
    RUNTIME_OVERHEAD_BYTES,
    Fit,
    FitEstimate,
    VramContext,
    describe,
    estimate_llamacpp,
    fit,
)
from zygos.models.gguf import GgufError, GgufHeader, read_header
from zygos.models.gguf_scan import GgufModel, scan_folder
from zygos.models.profile import ModelProfile, Sourced, record, resolve
from zygos.models.store import ProfileStore
from zygos.providers.base import Provider
# LOCAL_PROVIDERS is defined with the provider types and re-exported here.
from zygos.providers.types import LOCAL_PROVIDERS, OllamaModel, OllamaRunning, OllamaShow, ollama_name
from zygos.runtime.context import ExecutionContext
from zygos.runtime.events import ModelFit
from zygos.services.router import RouteChoice
from zygos.voice.service import VoiceState

log = logging.getLogger("zygos.models")

_ERROR_CHARS = 200
VLLM_FIT_TEXT = "fit not checked: vLLM reserves its GPU share at start"
# Page order: Ollama models, llama.cpp, vLLM (and other local routes), cloud.
_GROUP = {"ollama": 0, LLAMACPP_PROVIDER: 1}


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
    # llama.cpp (RFC-0014 §3, §4): the launch text in effect and where it came from.
    launch_text: str | None = None
    launch_source: Literal["model", "default"] | None = None
    launch_error: str | None = None
    mmproj: str | None = None  # paired projector, relative to the models folder
    mmproj_ambiguous: tuple[str, ...] = ()
    served_by: str | None = None  # vLLM address (RFC-0014 §9)
    # RFC-0013 §4: the route that will answer the next turn (saved default, else config primary).
    is_default: bool = False


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
    default: DefaultStatus


_ollama_name = ollama_name


def _entry_model(provider: str, model: str) -> str:
    return _ollama_name(model) if provider == "ollama" else model


def _value(profile: ModelProfile, key: str) -> Any:
    s = resolve(profile, key)
    return None if s is None else s.value


def _str(profile: ModelProfile, key: str) -> str | None:
    v = _value(profile, key)
    return v if isinstance(v, str) else None


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _order(entry: ModelEntry) -> tuple[Any, ...]:
    group = 3 if entry.location == "cloud" else _GROUP.get(entry.provider, 2)
    return group, entry.family is None, entry.family or "", entry.name


class _Vllm(BaseModel):
    """One view's read of the vLLM server."""

    url: str
    check: Check
    served: list[VllmModel]


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
        backends: BackendsStore | None = None,
        client: httpx.AsyncClient | None = None,
        read_header: Callable[[Path], GgufHeader] = read_header,
        default_status: Callable[[], DefaultStatus] | None = None,
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
        self._backends = backends
        self._client = client
        self._read_header = read_header
        self._default_status = default_status
        # llama.cpp model name -> (digest, reason) of a header that can't be
        # read: not re-read until its files change.
        self._gguf_failed: dict[str, tuple[str | None, str]] = {}
        # provider -> model names its last successful listing showed (RFC-0013 §5).
        self._installed: dict[str, frozenset[str]] = {}

    def installed(self, provider: str) -> frozenset[str] | None:
        """Names Ollama listed or vLLM served at the last successful read; None
        before one (unknown: trust a saved default) and for other providers."""
        return self._installed.get(provider)

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
        settings = await self._settings()
        entries: list[ModelEntry] = []
        ollama = self._providers.get("ollama")
        running: tuple[OllamaRunning, ...] = ()
        if ollama is None:
            status = OllamaStatus(configured=False, reachable=False, error=None)
            vllm = await self._read_vllm(settings)
        else:
            (tags, running, error), vllm = await asyncio.gather(
                self._read_ollama(ollama), self._read_vllm(settings))
            if error is not None:
                status = OllamaStatus(configured=True, reachable=False, error=error)
            else:
                status = OllamaStatus(configured=True, reachable=True, error=None)
                self._installed["ollama"] = frozenset(t.name for t in tags)
                entries.extend(await self._ollama_entries(ctx, ollama, tags, running, hardware))
        installed = {e.name for e in entries}
        entries.extend(await self._llamacpp_entries(ctx, settings.llamacpp, hardware, running))
        if vllm is not None:
            if vllm.check.ok:
                self._installed["vllm"] = frozenset(m.id for m in vllm.served)
            entries.extend(self._vllm_entries(vllm))
        listed = {(e.provider, e.name) for e in entries}
        entries.extend(self._route_entries(installed, ollama_reachable=status.reachable,
                                           listed=listed, vllm=vllm))
        entries.sort(key=_order)
        default = self._default()
        route = (default.route.provider, _entry_model(default.route.provider, default.route.model))
        marked = tuple(
            e.model_copy(update={"is_default": True}) if (e.provider, _entry_model(e.provider, e.name)) == route else e
            for e in entries)
        return ModelsView(hardware=hardware, ollama=status, models=marked, default=default)

    def _default(self) -> DefaultStatus:
        if self._default_status is not None:
            return self._default_status()
        p = self._config.providers.primary
        return DefaultStatus(source="config", route=RouteChoice(p.provider, p.model))

    async def _settings(self) -> BackendsSettings:
        if self._backends is None:
            return BackendsSettings()
        try:
            return await asyncio.to_thread(self._backends.get)
        except Exception as exc:  # noqa: BLE001 - the record never fails the view
            log.warning("backends record can't be read: %s", exc)
            return BackendsSettings()

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

    async def hardware_now(self) -> HardwareSnapshot:
        """A fresh hardware scan (residency's fit check, RFC-0013 §8); never raises."""
        return await asyncio.to_thread(self._hardware.scan)

    def reserve_bytes(self) -> int:
        """VRAM about to be taken by Kokoro on CUDA (see ``VramContext``)."""
        return self._reserve_bytes()

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

    def _route_entries(self, installed: set[str], *, ollama_reachable: bool,
                       listed: Collection[tuple[str, str]] = (),
                       vllm: _Vllm | None = None) -> list[ModelEntry]:
        """Configured routes not already listed: non-Ollama routes (a vLLM or
        llama.cpp route whose model a source listed is shown once, there), and
        Ollama routes missing from ``/api/tags`` (not installed, or Ollama is down)."""
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
            if key in seen or key in listed:
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
            if route.provider == "vllm" and vllm is not None:
                fit_text = (f"vLLM unreachable: {vllm.check.detail}" if not vllm.check.ok
                            else f"not served by vLLM at {vllm.url}")
            elif local:
                fit_text = f"fit not checked for {route.provider}"
            else:
                fit_text = "fit doesn't apply (cloud)"
            entries.append(self._entry(
                profile, provider=route.provider, name=route.model,
                location="local" if local else "cloud", loaded=False, vram_bytes=None, fitted=None,
                fit_text=fit_text, primary=key == primary, fallback=key in fallbacks))
        return entries

    # -- llama.cpp (RFC-0014 §3, §4) -------------------------------------------

    def _merged_header(self, model: GgufModel) -> GgufHeader:
        """The first part's header with every part's tensors (split sets)."""
        headers = [self._read_header(f) for f in model.files]
        first = headers[0]
        count = first.metadata.get("split.count")
        if isinstance(count, int) and not isinstance(count, bool) and count > len(headers):
            raise GgufError(f"split set has {len(headers)} of {count} parts")
        if len(headers) == 1:
            return first
        return first.model_copy(update={"tensors": tuple(t for h in headers for t in h.tensors)})

    def _build_gguf(self, model: GgufModel) -> ModelProfile:
        """Header read and profile build; runs in a worker thread."""
        return profile_from_gguf(model, self._merged_header(model), at=self._clock())

    async def _gguf_profile(self, model: GgufModel) -> tuple[ModelProfile, str | None]:
        """The model's profile (rebuilt only when its files changed) and, when
        its header can't be read, why."""
        digest = await asyncio.to_thread(gguf_digest, model)
        stored = self._profiles.get(LLAMACPP_PROVIDER, model.name)
        if stored is not None and digest is not None and stored.digest == digest:
            return stored, None
        fallback = stored or ModelProfile(provider=LLAMACPP_PROVIDER, model=model.name, names=[model.name])
        failed = self._gguf_failed.get(model.name)
        if failed is not None and failed[0] == digest:
            return fallback, failed[1]
        try:
            built = await asyncio.to_thread(self._build_gguf, model)
        except Exception as exc:  # noqa: BLE001 - one bad file never fails the scan
            reason = str(exc) if isinstance(exc, GgufError) else f"{type(exc).__name__}: {exc}"
            reason = reason[:_ERROR_CHARS]
            log.info("GGUF header of %s can't be read: %s", model.name, reason)
            self._gguf_failed[model.name] = (digest, reason)
            return fallback, reason
        self._gguf_failed.pop(model.name, None)
        if self._persisted(LLAMACPP_PROVIDER, [model.name], lambda: self._profiles.save(built)):
            saved = self._profiles.get(LLAMACPP_PROVIDER, model.name)
            if saved is not None and saved.digest == built.digest:
                return saved, None  # what is on disk, user section included
        return built, None

    async def _llamacpp_entries(
        self,
        ctx: ExecutionContext,
        lc: LlamaCppBackend,
        hardware: HardwareSnapshot,
        running: tuple[OllamaRunning, ...],
    ) -> list[ModelEntry]:
        if not lc.models_dir:
            return []
        root = Path(lc.models_dir)
        try:
            models = await asyncio.to_thread(scan_folder, root)
        except Exception as exc:  # noqa: BLE001 - an unreadable folder lists nothing
            log.warning("llama.cpp models folder %s can't be scanned: %s", root, exc)
            return []
        primary, fallbacks = self._route_keys()
        # Zygos frees Ollama's models before llama.cpp loads one (RFC-0014 §6).
        vram = VramContext(reclaimable_bytes=sum(r.size_vram for r in running),
                           reserve_bytes=self._reserve_bytes())
        entries: list[ModelEntry] = []
        for model in models:
            profile, header_error = await self._gguf_profile(model)
            text, source = effective_args(lc, model.name)
            launch_error: str | None = None
            fitted: Fit | None = None
            fit_text: str | None = None
            if header_error is None:
                try:
                    launch = read_launch(parse_launch(text))
                except LaunchError as exc:
                    launch_error = str(exc)
                    reason = f"launch settings: {launch_error}"
                    needs = FitEstimate(
                        model_bytes=None, context_bytes=None, context_tokens=0, context_assumed=False,
                        overhead_bytes=RUNTIME_OVERHEAD_BYTES, total_bytes=None, measured=False,
                        reason=reason)
                    fitted = fit(profile, hardware, vram, needs=needs)
                    fit_text = reason
                else:
                    fitted = fit(profile, hardware, vram, needs=estimate_llamacpp(profile, launch))
                    fit_text = describe(fitted)
                await ctx.emit(ModelFit(provider=LLAMACPP_PROVIDER, model=model.name, level=fitted.level,
                                        needs_bytes=fitted.needs.total_bytes,
                                        free_bytes=fitted.vram_available_bytes,
                                        measured=fitted.needs.measured), source="models")
            key = (LLAMACPP_PROVIDER, model.name)
            entries.append(self._entry(
                profile, provider=LLAMACPP_PROVIDER, name=model.name, location="local",
                loaded=False, vram_bytes=None, fitted=fitted, fit_text=fit_text,
                primary=key == primary, fallback=key in fallbacks,
                header_error=header_error, launch_text=text, launch_source=source,
                launch_error=launch_error,
                mmproj=None if model.mmproj is None else _rel(root, model.mmproj),
                mmproj_ambiguous=tuple(_rel(root, p) for p in model.mmproj_ambiguous)))
        return entries

    # -- vLLM (RFC-0014 §9) -----------------------------------------------------

    async def _read_vllm(self, settings: BackendsSettings) -> _Vllm | None:
        """A vLLM recorded or used by a route, read at the address startup resolves."""
        if self._client is None or not (settings.vllm or "vllm" in routed(self._config)):
            return None
        url = resolve_address(self._config, "vllm", settings)[0]
        check, served = await read_vllm(self._client, url)
        return _Vllm(url=url, check=check, served=served)

    def _vllm_profile(self, model: VllmModel) -> ModelProfile:
        key = ("vllm", model.id)
        before = self._profiles.get(*key)
        profile = before or ModelProfile(provider="vllm", model=model.id, names=[model.id])
        if model.max_model_len is not None:
            profile = record(profile, "identity.context_length_max", model.max_model_len, "server",
                             self._clock())
        if profile == before or key in self._save_tried or self._profiles.error_for(*key) is not None:
            return profile
        new = profile
        if self._persisted("vllm", [model.id], lambda: self._profiles.save(new)):
            saved = self._profiles.get(*key)
            if saved is None:
                self._save_tried.add(key)  # refused (a filename collision): warned once
                return profile
            return saved
        return profile

    def _vllm_entries(self, vllm: _Vllm) -> list[ModelEntry]:
        if not vllm.check.ok:
            profile = ModelProfile(provider="vllm", model=vllm.url, names=[vllm.url])
            return [self._entry(
                profile, provider="vllm", name=vllm.url, location="local", loaded=False,
                vram_bytes=None, fitted=None, fit_text=f"vLLM unreachable: {vllm.check.detail}",
                primary=False, fallback=False, served_by=vllm.url)]
        primary, fallbacks = self._route_keys()
        entries: list[ModelEntry] = []
        for model in vllm.served:
            key = ("vllm", model.id)
            entries.append(self._entry(
                self._vllm_profile(model), provider="vllm", name=model.id, location="local",
                loaded=False, vram_bytes=None, fitted=None, fit_text=VLLM_FIT_TEXT,
                primary=key == primary, fallback=key in fallbacks, served_by=vllm.url))
        return entries

    def _entry(self, profile: ModelProfile, *, provider: str, name: str, location: Literal["local", "cloud"],
               loaded: bool, vram_bytes: int | None, fitted: Fit | None, fit_text: str | None,
               primary: bool, fallback: bool, header_error: str | None = None,
               launch_text: str | None = None, launch_source: Literal["model", "default"] | None = None,
               launch_error: str | None = None, mmproj: str | None = None,
               mmproj_ambiguous: tuple[str, ...] = (), served_by: str | None = None) -> ModelEntry:
        keys = sorted({*profile.values, *profile.user})
        fields = {k: s for k in keys if (s := resolve(profile, k)) is not None}
        specialty = _value(profile, "identity.specialty")
        size = _value(profile, "identity.download_size_bytes")
        error = self._profiles.error_for(provider, name)
        save_error = self._save_errors.get((provider, name))
        if header_error is not None:
            profile_error: str | None = f"can't read GGUF header: {header_error}"
        elif error is not None:
            profile_error = f"profile file can't be read: {error.reason[:_ERROR_CHARS]}"
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
            fields=fields, launch_text=launch_text, launch_source=launch_source,
            launch_error=launch_error, mmproj=mmproj, mmproj_ambiguous=mmproj_ambiguous,
            served_by=served_by)
