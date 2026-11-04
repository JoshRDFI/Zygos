from zygos.api.speech_stream import SpeechPacer


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _pacer():
    c = Clock()
    return c, SpeechPacer(clock=c)


def _sentence(n, first=""):
    words = ([first] if first else []) + ["w"] * (n - (1 if first else 0))
    return " ".join(words)


def test_fast_writer_starts_at_first_sentence_with_enough_words():
    c, p = _pacer()
    assert p.feed("One") == []
    c.t = 0.15
    out = p.feed(" two three four five six seven eight nine. ")
    assert out == ["One two three four five six seven eight nine."]
    assert p.started is True
    assert p.words_at_start == 9


def test_never_starts_below_min_words():
    c, p = _pacer()
    c.t = 0.01
    assert p.feed("Yes. ") == []
    assert p.started is False


def test_slow_writer_waits_per_formula():
    c, p = _pacer()
    assert p.feed("One") == []
    for k in range(1, 8):
        c.t = 2.0 * k
        rest = " w" * 9 + ". "
        assert p.feed(rest) == [], k
        assert p.started is False
        # next sentence's first word arrives with the next feed
        p.feed("One")
    c.t = 16.0
    out = p.feed(" w" * 9 + ". ")
    assert len(out) == 8
    assert p.started is True
    assert p.words_at_start == 80


def test_short_reply_released_only_at_finish():
    c, p = _pacer()
    assert p.feed("Hi there.") == []
    assert p.finish() == ["Hi there."]


def test_newline_is_a_boundary():
    c, p = _pacer()
    p.feed("One")
    c.t = 0.1
    p.feed(" two three four five six seven eight nine. ")
    assert p.started
    assert p.feed("- one\n") == ["- one"]


def test_no_boundary_waits_for_finish():
    c, p = _pacer()
    for i in range(300):
        c.t = i * 0.01
        assert p.feed("word ") == []
    out = p.finish()
    assert len(out) == 1
    assert len(out[0].split()) == 300


def test_flush_complete_drops_fragment():
    c, p = _pacer()
    p.feed("A b c. D e")
    assert p.flush_complete() == ["A b c."]


def test_clock_starts_at_first_text():
    c, p = _pacer()
    c.t = 0.0
    p.feed("")
    c.t = 10.0
    p.feed("One")
    c.t = 11.0
    assert p.feed(" w" * 8 + ". ") == []  # r=9: 4.0 < 21.2
    p.finish()
    assert p.rate_wps == 9.0
    assert p.words_at_start == 9


def test_single_chunk_reply_t_zero_starts():
    c, p = _pacer()
    c.t = 5.0
    out = p.feed("One two three four five six seven eight. Nine. ")
    assert len(out) == 2
    assert p.started
    assert p.rate_wps is None


# --- StreamingSpeaker -------------------------------------------------------------------

import asyncio

import pytest

from zygos.api.frames import AUDIO_OUT, AUDIO_TAG_OUT
from zygos.api.session import Session
from zygos.api.speech_stream import StreamingSpeaker
from zygos.runtime.context import CancelToken, root_context
from zygos.runtime.events import InProcessEventBus
from zygos.voice.errors import SynthesisFailed
from zygos.voice.types import AudioFormat


class _Synth:
    def __init__(self, chunks, hook=None, raise_at=None):
        self._chunks = chunks
        self._hook = hook
        self._raise_at = raise_at
        self.cancel_called = False
        self.closed = False

    async def chunks(self):
        for i, c in enumerate(self._chunks):
            if self._raise_at == i:
                raise SynthesisFailed("boom")
            if self._hook:
                self._hook(i)
            yield c
            await asyncio.sleep(0)

    async def cancel(self):
        self.cancel_called = True

    async def aclose(self):
        self.closed = True


class _Voice:
    tts_available = True

    def __init__(self, synths):
        self.synths = synths  # text -> _Synth
        self.texts = []
        self.made = {}

    @property
    def tts_format(self):
        return AudioFormat(sample_rate=24000)

    def synthesize_stream(self, ctx, text):
        self.texts.append(text)
        s = self.synths.get(text) or _Synth([b"\x00\x00"])
        self.made[text] = s
        return s


def _sess():
    s = Session("s", root_context(InProcessEventBus()), created_at=0.0)
    s.speak = True  # a speaker only exists while Speaker is on
    return s


def _frames(session):
    out = []
    while not session.outbound.empty():
        out.append(session.outbound.get_nowait())
    return out


def _types(items):
    return [i.type if hasattr(i, "type") else "pcm" for i in items]


def _speaker(session, voice, *, token=None, bus=None, clock=None, wait_for=None, started=0.0):
    ctx = root_context(bus or InProcessEventBus()).child("t", cancel=token or CancelToken())
    kw = {} if clock is None else {"clock": clock}
    return StreamingSpeaker(session, voice, ctx, "turn-1", turn_started_at=started,
                            wait_for=wait_for, **kw)


async def test_one_begin_and_end_for_many_sentences():
    s = _sess()
    v = _Voice({})
    sp = _speaker(s, v)
    sp.say(["A.", "B."])
    await sp.close(SpeechPacer())
    items = _frames(s)
    assert _types(items) == ["tts.begin", "pcm", "pcm", "tts.end"]
    assert items[0].channel == AUDIO_OUT
    assert items[0].payload == {"sample_rate": 24000, "channels": 1,
                                "sample_format": "s16le", "turn_id": "turn-1"}
    assert items[1][0] == AUDIO_TAG_OUT
    assert items[-1].payload == {"turn_id": "turn-1", "reason": "complete"}
    assert v.texts == ["A.", "B."]
    assert s.speaking is False


async def test_synth_cancel_and_aclose_called_per_sentence():
    s = _sess()
    v = _Voice({})
    sp = _speaker(s, v)
    sp.say(["A.", "B."])
    await sp.close(SpeechPacer())
    assert all(m.cancel_called and m.closed for m in v.made.values()) and len(v.made) == 2


async def test_waits_for_prefix_before_begin():
    s = _sess()
    gate = asyncio.Event()

    async def prefix():
        await gate.wait()

    task = asyncio.create_task(prefix())
    sp = _speaker(s, _Voice({}), wait_for=task)
    sp.say(["A."])
    for _ in range(5):
        await asyncio.sleep(0)
    assert _frames(s) == []
    gate.set()
    await sp.close(SpeechPacer())
    assert _types(_frames(s)) == ["tts.begin", "pcm", "tts.end"]


async def test_synthesis_error_ends_error_and_stops():
    s = _sess()
    v = _Voice({"B.": _Synth([b"\x00"], raise_at=0)})
    sp = _speaker(s, v)
    sp.say(["A.", "B.", "C."])
    await sp.close(SpeechPacer())  # must not raise
    items = _frames(s)
    assert items[-1].type == "tts.end" and items[-1].payload["reason"] == "error"
    assert _types(items).count("tts.end") == 1
    assert v.texts == ["A.", "B."]


async def test_cancel_mid_sentence_ends_cancelled():
    s = _sess()
    token = CancelToken()
    v = _Voice({"A.": _Synth([b"\x00", b"\x01", b"\x02"],
                             hook=lambda i: token.trip() if i == 1 else None)})
    sp = _speaker(s, v, token=token)
    sp.say(["A.", "B."])
    await sp.close(SpeechPacer())
    items = _frames(s)
    assert _types(items).count("pcm") == 1
    assert items[-1].payload["reason"] == "cancelled"
    assert v.texts == ["A."]


async def test_abort_while_idle_ends_cancelled_once():
    s = _sess()
    sp = _speaker(s, _Voice({}))
    sp.say(["A."])
    for _ in range(10):
        await asyncio.sleep(0)
    await sp.abort()
    await sp.abort()
    ends = [i for i in _frames(s) if getattr(i, "type", None) == "tts.end"]
    assert len(ends) == 1 and ends[0].payload["reason"] == "cancelled"


async def test_nothing_said_sends_nothing():
    s = _sess()
    bus = InProcessEventBus()
    seen = []

    async def sub(e):
        seen.append(e)

    bus.subscribe(sub)
    sp = _speaker(s, _Voice({}), bus=bus)
    await sp.close(SpeechPacer())
    assert _frames(s) == [] and seen == []


class _Clock:
    t = 0.0

    def __call__(self):
        return self.t


async def _timing(synths, sentences, clock, pacer=None):
    s = _sess()
    bus = InProcessEventBus()
    seen = []

    async def sub(e):
        seen.append(e)

    bus.subscribe(sub)
    sp = _speaker(s, _Voice(synths), bus=bus, clock=clock)
    sp.say(sentences)
    await sp.close(pacer or SpeechPacer())
    return [e for e in seen if e.payload.type == "speech.timing"]


async def test_speech_timing_emitted():
    clock = _Clock()
    clock.t = 2.0
    pacer = SpeechPacer(clock=clock)
    pacer._words_at_start, pacer._rate_wps = 14, 51.96
    # 1 second of mono 24k s16 PCM per sentence; the clock never advances past the projection.
    sec = b"\x00" * 48000
    evs = await _timing({"A.": _Synth([sec]), "B.": _Synth([sec])}, ["A.", "B."], clock, pacer)
    assert len(evs) == 1
    p = evs[0].payload
    assert evs[0].source == "speech"
    assert (p.turn_id, p.first_audio_ms, p.words_at_start, p.rate_wps) == ("turn-1", 2000, 14, 52.0)
    assert (p.gaps, p.gap_ms, p.reason) == (0, 0, "complete")


async def test_speech_timing_estimates_gap():
    clock = _Clock()
    sec = b"\x00" * 48000

    def late(i):
        clock.t = 4.5  # projected playback end is 0 + 1s; first chunk of B arrives at 4.5

    evs = await _timing({"A.": _Synth([sec]), "B.": _Synth([sec], hook=late)},
                        ["A.", "B."], clock)
    p = evs[0].payload
    assert p.first_audio_ms == 0 and p.gaps == 1 and p.gap_ms == 3500


async def test_speech_timing_null_when_nothing_synthesized_and_cancelled_reason():
    clock = _Clock()
    s = _sess()
    token = CancelToken()
    token.trip()
    bus = InProcessEventBus()
    seen = []

    async def sub(e):
        seen.append(e)

    bus.subscribe(sub)
    sp = _speaker(s, _Voice({}), token=token, bus=bus, clock=clock)
    sp.say(["A."])
    await sp.close(SpeechPacer())
    # cancelled before tts.begin: nothing sent, no event
    assert _frames(s) == [] and seen == []


class _RaisingVoice(_Voice):
    def synthesize_stream(self, ctx, text):
        self.texts.append(text)
        raise SynthesisFailed("no engine")


async def test_synthesize_stream_raising_ends_error():
    s = _sess()
    v = _RaisingVoice({})
    sp = _speaker(s, v)
    sp.say(["A.", "B."])
    await sp.close(SpeechPacer())  # must not raise
    items = _frames(s)
    assert _types(items) == ["tts.begin", "tts.end"]
    assert items[-1].payload["reason"] == "error"
    assert v.texts == ["A."]


async def test_abort_after_synthesize_failure_does_not_raise():
    s = _sess()
    sp = _speaker(s, _RaisingVoice({}))
    sp.say(["A."])
    for _ in range(10):
        await asyncio.sleep(0)
    await sp.abort()
    ends = [i for i in _frames(s) if getattr(i, "type", None) == "tts.end"]
    assert len(ends) == 1
    assert ends[0].payload["reason"] == "error"  # M1: a later abort keeps the error reason


# --- Final review fixes (M1, M3, M4) -------------------------------------------------------

async def test_speaking_false_right_after_synthesis_failure():
    s = _sess()
    v = _RaisingVoice({})
    sp = _speaker(s, v)
    sp.say(["A."])
    await _until_true(lambda: v.texts == ["A."] and sp._task.done())
    assert s.speaking is False  # before close: no duck for audio that isn't playing
    sp.say(["B."])  # dropped once the reason is error
    for _ in range(5):
        await asyncio.sleep(0)
    assert v.texts == ["A."]
    assert sp._queue.empty()
    await sp.close(SpeechPacer())
    ends = [i for i in _frames(s) if getattr(i, "type", None) == "tts.end"]
    assert len(ends) == 1 and ends[0].payload["reason"] == "error"


async def _until_true(pred, n=200):
    for _ in range(n):
        if pred():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never became true")


class _SlowCancelSynth(_Synth):
    """Synthesizes until cancelled, then takes several ticks to unwind."""

    def __init__(self, started):
        super().__init__([])
        self._started = started

    async def chunks(self):
        self._started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            for _ in range(5):
                try:
                    await asyncio.sleep(0)
                except asyncio.CancelledError:
                    pass
            raise
        yield b""  # pragma: no cover


async def test_abort_propagates_caller_cancellation_after_one_end():
    s = _sess()
    started = asyncio.Event()
    v = _Voice({"A.": _SlowCancelSynth(started)})
    sp = _speaker(s, v)
    sp.say(["A."])
    await asyncio.wait_for(started.wait(), 1.0)
    caller = asyncio.create_task(sp.abort(SpeechPacer()))
    await asyncio.sleep(0)  # caller is now awaiting the slow-to-cancel consumer
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    ends = [i for i in _frames(s) if getattr(i, "type", None) == "tts.end"]
    assert len(ends) == 1 and ends[0].payload["reason"] == "cancelled"


async def test_speaker_off_mid_reply_stops_at_next_sentence():
    s = _sess()
    s.speak = True
    v = _Voice({"A.": _Synth([b"\x00\x00"], hook=lambda i: setattr(s, "speak", False))})
    sp = _speaker(s, v)
    sp.say(["A.", "B.", "C."])
    await sp.close(SpeechPacer())
    items = _frames(s)
    assert v.texts == ["A."]
    ends = [i for i in items if getattr(i, "type", None) == "tts.end"]
    assert len(ends) == 1 and ends[0].payload["reason"] == "cancelled"
    assert s.speaking is False
