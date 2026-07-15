from __future__ import annotations

from zygos.api.frames import AUDIO_OUT, AUDIO_TAG_OUT
from zygos.api.session import Session
from zygos.api.speech import speak_reply
from zygos.runtime.context import CancelToken, root_context
from zygos.runtime.events import InProcessEventBus
from zygos.voice.errors import SynthesisFailed
from zygos.voice.types import AudioFormat


class _StubSynth:
    def __init__(self, chunks, token=None, cancel_after=None, raise_after=None,
                 cancel_raises=False):
        self._chunks = chunks
        self._token = token
        self._cancel_after = cancel_after
        self._raise_after = raise_after
        self._cancel_raises = cancel_raises
        self.cancel_called = False
        self.closed = False

    async def chunks(self):
        for i, c in enumerate(self._chunks):
            if self._token is not None and self._token.is_set:
                return
            if self._raise_after is not None and i == self._raise_after:
                raise SynthesisFailed("boom")
            yield c
            if self._cancel_after is not None and i == self._cancel_after and self._token:
                self._token.trip()

    async def cancel(self):
        self.cancel_called = True
        if self._cancel_raises:
            raise SynthesisFailed("teardown boom")

    async def aclose(self):
        self.closed = True


class _StubSynthLoopBreak:
    """Yields chunks unconditionally and trips the token mid-stream without any
    internal check in `chunks()` — exercises speak_reply's own
    `if ctx.cancelled: break` line, as opposed to a generator that stops itself."""

    def __init__(self, chunks, token):
        self._chunks = chunks
        self._token = token
        self.cancel_called = False
        self.closed = False

    async def chunks(self):
        for i, c in enumerate(self._chunks):
            yield c
            if i == 0:
                self._token.trip()

    async def cancel(self):
        self.cancel_called = True

    async def aclose(self):
        self.closed = True


class _StubVoice:
    def __init__(self, synth):
        self._synth = synth
        self.tts_available = True
    @property
    def tts_format(self):
        return AudioFormat(sample_rate=24000)
    def synthesize_stream(self, ctx, text):
        return self._synth


def _session():
    return Session("s", root_context(InProcessEventBus()), created_at=0.0)


def _drain(session):
    out = []
    while not session.outbound.empty():
        out.append(session.outbound.get_nowait())
    return out


async def test_happy_path_emits_begin_chunks_end_complete():
    session = _session()
    synth = _StubSynth([b"\x00\x00", b"\x11\x11", b"\x22\x22"])
    ctx = root_context(InProcessEventBus())
    await speak_reply(session, _StubVoice(synth), ctx, "hello", "t1")
    items = _drain(session)
    assert items[0].type == "tts.begin" and items[0].channel == AUDIO_OUT
    assert items[0].payload["sample_rate"] == 24000 and items[0].payload["turn_id"] == "t1"
    audio = [i for i in items if isinstance(i, (bytes, bytearray))]
    assert len(audio) == 3 and audio[0] == bytes([AUDIO_TAG_OUT]) + b"\x00\x00"
    assert items[-1].type == "tts.end" and items[-1].payload["reason"] == "complete"
    assert synth.closed is True


async def test_barge_in_ends_cancelled():
    session = _session()
    token = CancelToken()
    ctx = root_context(InProcessEventBus()).child("t", cancel=token)
    synth = _StubSynth([b"\x00", b"\x01", b"\x02"], token=token, cancel_after=0)
    await speak_reply(session, _StubVoice(synth), ctx, "hi", "t2")
    items = _drain(session)
    audio = [i for i in items if isinstance(i, (bytes, bytearray))]
    assert len(audio) == 1  # broke after the first chunk
    assert items[-1].type == "tts.end" and items[-1].payload["reason"] == "cancelled"
    assert synth.cancel_called is True


async def test_synthesis_failure_ends_error_without_raising():
    session = _session()
    ctx = root_context(InProcessEventBus())
    synth = _StubSynth([b"\x00"], raise_after=0)
    await speak_reply(session, _StubVoice(synth), ctx, "hi", "t3")  # must not raise
    items = _drain(session)
    assert items[-1].type == "tts.end" and items[-1].payload["reason"] == "error"


async def test_loop_body_break_on_cancelled_ends_cancelled():
    # ctx.cancelled becomes true only between iterations of speak_reply's own
    # loop body (not inside the generator), exercising `if ctx.cancelled: break`
    # directly rather than the generator returning early (test_barge_in_ends_cancelled).
    session = _session()
    token = CancelToken()
    ctx = root_context(InProcessEventBus()).child("t", cancel=token)
    synth = _StubSynthLoopBreak([b"\x00", b"\x01", b"\x02"], token)
    await speak_reply(session, _StubVoice(synth), ctx, "hi", "t4")
    items = _drain(session)
    audio = [i for i in items if isinstance(i, (bytes, bytearray))]
    assert len(audio) == 1  # chunk 0 enqueued; loop breaks before chunk 1
    assert items[-1].type == "tts.end" and items[-1].payload["reason"] == "cancelled"


async def test_teardown_failure_does_not_prevent_tts_end():
    # synth.cancel() raising (e.g. a dead sidecar) must not skip the tts.end frame
    # or escape speak_reply.
    session = _session()
    ctx = root_context(InProcessEventBus())
    synth = _StubSynth([b"\x00", b"\x01"], cancel_raises=True)
    await speak_reply(session, _StubVoice(synth), ctx, "hi", "t5")  # must not raise
    items = _drain(session)
    assert synth.cancel_called is True
    assert items[-1].type == "tts.end" and items[-1].payload["reason"] == "complete"
