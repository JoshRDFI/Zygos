from __future__ import annotations

import asyncio
import logging

from zygos.runtime.context import ExecutionContext
from zygos.voice.contract import SttHealth, TtsHealth
from zygos.voice.errors import SynthesisFailed, TranscriptionFailed, VoiceError
from zygos.voice.ipc import IpcConnection
from zygos.voice.sidecar import SidecarHandle
from zygos.voice.types import AudioFormat, SttEngineSpec, TranscriptEvent, TtsEngineSpec


_log = logging.getLogger(__name__)

_DRAIN_TERMINALS = frozenset({"end", "final", "error", "cancelled"})


async def _await_ready(conn: IpcConnection, name: str,
                       timeout_s: float) -> tuple[str | None, str | None]:
    """Readiness handshake. Returns the (device, reason) the worker reported, if any.

    A worker that dies hard mid-startup (CUDA abort/segfault/OOM kill) can surface
    as EOFError *or* OSError (BrokenPipeError/ConnectionResetError, e.g. Linux UDS
    when the health frame is unread in the dead worker's receive queue) from either
    send_control or recv, depending on timing — both must map to the same
    VoiceError so a caller with a CPU fallback can retry instead of failing voice
    startup outright.
    """
    try:
        await conn.send_control({"type": "health"})
        _kind, body = await asyncio.wait_for(conn.recv(), timeout_s)
    except asyncio.TimeoutError as exc:
        raise VoiceError(f"{name} not ready within {timeout_s}s") from exc
    except (EOFError, OSError) as exc:
        raise VoiceError(f"{name} exited before reporting ready") from exc
    if not (isinstance(body, dict) and body.get("type") == "health_ok"):
        raise VoiceError(f"{name} unexpected readiness reply: {body!r}")
    return body.get("device"), body.get("reason")


async def _drain_to_terminal(conn: IpcConnection, *, poll_s: float = 0.05,
                             budget_s: float = 2.0) -> None:
    """Discard frames until a terminal control or EOF, bounded by budget_s.

    Best-effort: after a barge-in `cancel`, the worker emits its terminal
    promptly, so the terminal arrives within a poll. On a wedged/dead worker we
    give up within budget_s (the sidecar supervisor respawns it; the
    single-session gate prevents cross-session bleed).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return
        try:
            kind, body = await asyncio.wait_for(conn.recv(), min(poll_s, remaining))
        except asyncio.TimeoutError:
            continue
        except EOFError:
            return
        if kind == "control" and body.get("type") in _DRAIN_TERMINALS:
            return


class Transcription:
    """One in-flight utterance over the sidecar's shared connection."""

    def __init__(self, conn: IpcConnection) -> None:
        self._conn = conn
        self._started = False
        self._done = False

    async def _ensure_started(self) -> None:
        if not self._started:
            await self._conn.send_control({"type": "start", "sample_rate": 16000})
            self._started = True

    async def push(self, pcm: bytes) -> None:
        await self._ensure_started()
        await self._conn.send_pcm(pcm)

    async def endpoint(self) -> None:
        await self._ensure_started()
        await self._conn.send_control({"type": "end"})

    async def cancel(self) -> None:
        if self._started and not self._done:
            await self._conn.send_control({"type": "cancel"})
            await _drain_to_terminal(self._conn)
        self._done = True

    async def events(self):
        try:
            while not self._done:
                kind, body = await self._conn.recv()
                if kind != "control":
                    continue
                mtype = body.get("type")
                if mtype == "partial":
                    yield TranscriptEvent(kind="partial", text=body.get("text", ""))
                elif mtype == "final":
                    self._done = True
                    yield TranscriptEvent(kind="final", text=body.get("text", ""))
                elif mtype == "error":
                    self._done = True
                    raise TranscriptionFailed(body.get("message", "sidecar error"))
        except EOFError as exc:
            self._done = True
            raise TranscriptionFailed("sidecar closed mid-utterance") from exc

    async def aclose(self) -> None:
        self._done = True


class SttPlugin:
    """Concrete STT engine adapter. Satisfies the SpeechToText contract."""

    def __init__(self, spec: SttEngineSpec, *, readiness_timeout_s: float = 60.0) -> None:
        self._spec = spec
        self._handle = SidecarHandle(spec)
        self._started = False
        self._readiness_timeout_s = readiness_timeout_s

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def concurrent_safe(self) -> bool:
        return self._spec.concurrent_safe

    async def start(self) -> None:
        await self._handle.start()
        await _await_ready(self._handle.connection, self._spec.name, self._readiness_timeout_s)
        self._started = True

    async def ensure_alive(self) -> None:
        await self._handle.ensure_alive()

    def begin(self, ctx: ExecutionContext) -> Transcription:
        return Transcription(self._handle.connection)

    def health(self) -> SttHealth:
        st = self._handle.snapshot()
        return SttHealth(engine=st.engine, device=st.device, alive=st.alive,
                         last_error=st.last_error, requested_device=st.device)

    async def aclose(self) -> None:
        await self._handle.aclose()
        self._started = False


class Synthesis:
    """One in-flight synthesis over the TTS sidecar's shared connection.

    chunks() polls ctx.cancelled on a short timeout so a barge-in unwinds it
    within poll_s even while blocked waiting for the next sidecar frame.
    """

    def __init__(self, conn: IpcConnection, ctx: ExecutionContext, *,
                 text: str, sample_rate: int, poll_s: float = 0.05) -> None:
        self._conn = conn
        self._ctx = ctx
        self._text = text
        self._sample_rate = sample_rate
        self._poll_s = poll_s
        self._started = False
        self._done = False

    async def _ensure_started(self) -> None:
        if not self._started:
            await self._conn.send_control(
                {"type": "synthesize", "text": self._text, "sample_rate": self._sample_rate})
            self._started = True

    async def chunks(self):
        await self._ensure_started()
        try:
            while not self._done:
                if self._ctx.cancelled:
                    await self.cancel()
                    return
                try:
                    kind, body = await asyncio.wait_for(self._conn.recv(), self._poll_s)
                except asyncio.TimeoutError:
                    continue  # re-check ctx.cancelled
                if kind == "pcm":
                    yield body
                    continue
                mtype = body.get("type")
                if mtype == "end":
                    self._done = True
                elif mtype == "error":
                    self._done = True
                    raise SynthesisFailed(body.get("message", "sidecar error"))
        except EOFError as exc:
            self._done = True
            raise SynthesisFailed("sidecar closed mid-synthesis") from exc

    async def cancel(self) -> None:
        if self._started and not self._done:
            await self._conn.send_control({"type": "cancel"})
            await _drain_to_terminal(self._conn)
        self._done = True

    async def aclose(self) -> None:
        self._done = True


class TtsPlugin:
    """Concrete TTS engine adapter. Satisfies the TextToSpeech contract."""

    def __init__(self, spec: TtsEngineSpec, *, readiness_timeout_s: float = 60.0,
                 fallback_spec: TtsEngineSpec | None = None,
                 requested_device: str | None = None,
                 launch_reason: str | None = None) -> None:
        self._spec = spec
        self._handle = SidecarHandle(spec)
        self._started = False
        self._readiness_timeout_s = readiness_timeout_s
        self._fallback_spec = fallback_spec
        self._requested_device = requested_device or spec.device
        self._active_device = spec.device
        self._fallback_reason = launch_reason

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def concurrent_safe(self) -> bool:
        return self._spec.concurrent_safe

    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=self._spec.output_sample_rate)

    async def _start_handle(self) -> tuple[str | None, str | None]:
        await self._handle.start()
        return await _await_ready(self._handle.connection, self._spec.name,
                                  self._readiness_timeout_s)

    async def start(self) -> None:
        try:
            device, worker_reason = await self._start_handle()
        except VoiceError as exc:
            if self._fallback_spec is None:
                raise
            await self._handle.aclose()
            self._spec, self._fallback_spec = self._fallback_spec, None
            self._handle = SidecarHandle(self._spec)
            self._fallback_reason = self._fallback_reason or f"GPU worker failed to start: {exc}"
            device, worker_reason = await self._start_handle()
        self._active_device = device or self._spec.device
        self._fallback_reason = self._fallback_reason or worker_reason
        if self._active_device != self._requested_device:
            _log.warning("%s: requested device %s, running on %s (%s)", self._spec.name,
                         self._requested_device, self._active_device, self._fallback_reason)
        self._started = True

    def synthesize(self, ctx: ExecutionContext, text: str) -> Synthesis:
        return Synthesis(self._handle.connection, ctx,
                         text=text, sample_rate=self._spec.output_sample_rate)

    def health(self) -> TtsHealth:
        st = self._handle.snapshot()
        return TtsHealth(engine=st.engine, device=self._active_device, alive=st.alive,
                         last_error=st.last_error, requested_device=self._requested_device,
                         fallback_reason=self._fallback_reason)

    async def aclose(self) -> None:
        await self._handle.aclose()
        self._started = False
