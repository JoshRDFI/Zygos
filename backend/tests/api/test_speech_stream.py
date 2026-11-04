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
