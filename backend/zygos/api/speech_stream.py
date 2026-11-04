"""Decides when a streamed reply may start being spoken (sentence-streaming speech).

SpeechPacer is pure: no I/O, no asyncio. It is fed streamed text and releases complete
sentences for synthesis only once speech can start without running dry mid-reply: the
words spoken before the writer catches up must cover the time the remaining (assumed)
words will take to arrive at the measured writing rate.

Stability: Experimental.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable

SPEAKING_RATE_WPS = 3.0
ASSUMED_REPLY_WORDS = 200
START_MARGIN_S = 1.0
MIN_START_WORDS = 8

_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n")


def _words(sentences: list[str]) -> int:
    return sum(len(s.split()) for s in sentences)


class SpeechPacer:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._t0: float | None = None
        self._buf = ""
        self._pending: list[str] = []
        self._started = False
        self._words_at_start: int | None = None
        self._rate_wps: float | None = None

    @property
    def started(self) -> bool:
        return self._started

    @property
    def words_at_start(self) -> int | None:
        return self._words_at_start

    @property
    def rate_wps(self) -> float | None:
        return self._rate_wps

    def _rate(self, words: int) -> float | None:
        if self._t0 is None:
            return None
        t = self._clock() - self._t0
        return words / t if t > 0 else None

    def _split(self) -> list[str]:
        parts = _BOUNDARY.split(self._buf)
        self._buf = parts[-1]
        return [p.strip() for p in parts[:-1] if p.strip()]

    def feed(self, text: str) -> list[str]:
        if not text:
            return []
        if self._t0 is None and text.strip():
            self._t0 = self._clock()
        self._buf += text
        new = self._split()
        if not new:
            return []
        if self._started:
            return new
        self._pending.extend(new)
        w = _words(self._pending)
        if w < MIN_START_WORDS:
            return []
        r = self._rate(w)
        remaining = max(ASSUMED_REPLY_WORDS - w, 0)
        needed = remaining / r if r is not None else 0.0
        if w / SPEAKING_RATE_WPS + START_MARGIN_S < needed:
            return []
        self._started = True
        self._words_at_start = w
        self._rate_wps = r
        out, self._pending = self._pending, []
        return out

    def _drain(self, sentences: list[str]) -> list[str]:
        out = self._pending + sentences
        self._pending = []
        if not self._started:
            self._words_at_start = _words(out)
            self._rate_wps = self._rate(self._words_at_start)
        return out

    def finish(self) -> list[str]:
        sentences = self._split()
        tail = self._buf.strip()
        self._buf = ""
        if tail:
            sentences.append(tail)
        return self._drain(sentences)

    def flush_complete(self) -> list[str]:
        sentences = self._split()
        self._buf = ""
        return self._drain(sentences)
