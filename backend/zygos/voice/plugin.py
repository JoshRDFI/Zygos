from __future__ import annotations

from zygos.runtime.context import ExecutionContext
from zygos.voice.contract import SttHealth
from zygos.voice.errors import TranscriptionFailed
from zygos.voice.ipc import IpcConnection
from zygos.voice.sidecar import SidecarHandle
from zygos.voice.types import SttEngineSpec, TranscriptEvent


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

    def __init__(self, spec: SttEngineSpec) -> None:
        self._spec = spec
        self._handle = SidecarHandle(spec)
        self._started = False

    @property
    def name(self) -> str:
        return self._spec.name

    async def start(self) -> None:
        await self._handle.start()
        self._started = True

    def begin(self, ctx: ExecutionContext) -> Transcription:
        return Transcription(self._handle.connection)

    def health(self) -> SttHealth:
        st = self._handle.snapshot()
        return SttHealth(engine=st.engine, device=st.device, alive=st.alive, last_error=st.last_error)

    async def aclose(self) -> None:
        await self._handle.aclose()
        self._started = False
