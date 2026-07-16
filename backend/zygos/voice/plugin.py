from __future__ import annotations

import asyncio

from zygos.runtime.context import ExecutionContext
from zygos.voice.contract import SttHealth, TtsHealth
from zygos.voice.errors import SynthesisFailed, TranscriptionFailed, VoiceError
from zygos.voice.ipc import IpcConnection
from zygos.voice.sidecar import SidecarHandle
from zygos.voice.types import AudioFormat, SttEngineSpec, TranscriptEvent, TtsEngineSpec


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
        conn = self._handle.connection
        await conn.send_control({"type": "health"})
        try:
            _kind, body = await asyncio.wait_for(conn.recv(), self._readiness_timeout_s)
        except asyncio.TimeoutError as exc:
            raise VoiceError(
                f"{self._spec.name} not ready within {self._readiness_timeout_s}s") from exc
        if not (isinstance(body, dict) and body.get("type") == "health_ok"):
            raise VoiceError(f"{self._spec.name} unexpected readiness reply: {body!r}")
        self._started = True

    async def ensure_alive(self) -> None:
        await self._handle.ensure_alive()

    def begin(self, ctx: ExecutionContext) -> Transcription:
        return Transcription(self._handle.connection)

    def health(self) -> SttHealth:
        st = self._handle.snapshot()
        return SttHealth(engine=st.engine, device=st.device, alive=st.alive, last_error=st.last_error)

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
        self._done = True

    async def aclose(self) -> None:
        self._done = True


class TtsPlugin:
    """Concrete TTS engine adapter. Satisfies the TextToSpeech contract."""

    def __init__(self, spec: TtsEngineSpec) -> None:
        self._spec = spec
        self._handle = SidecarHandle(spec)
        self._started = False

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def concurrent_safe(self) -> bool:
        return self._spec.concurrent_safe

    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=self._spec.output_sample_rate)

    async def start(self) -> None:
        await self._handle.start()
        self._started = True

    def synthesize(self, ctx: ExecutionContext, text: str) -> Synthesis:
        return Synthesis(self._handle.connection, ctx,
                         text=text, sample_rate=self._spec.output_sample_rate)

    def health(self) -> TtsHealth:
        st = self._handle.snapshot()
        return TtsHealth(engine=st.engine, device=st.device, alive=st.alive, last_error=st.last_error)

    async def aclose(self) -> None:
        await self._handle.aclose()
        self._started = False
