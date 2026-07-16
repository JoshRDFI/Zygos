"""Real TTS worker backed by kokoro-onnx (ONNX Runtime), CPU-first.

Run as: python -m zygos.voice.sidecar.kokoro <address>
Speaks the same length-prefixed IPC contract as fake_tts. Only synthesis is real.
kokoro_onnx is imported lazily so this module imports (for the pure helpers)
without the optional `voice` extra installed. No misaki — kokoro-onnx's built-in
tokenizer phonemizes raw text via espeakng-loader/phonemizer-fork (torch-free).

Synthesis is sentence-level: each sentence is synthesized and streamed as a
KIND_PCM frame, terminated by a single `end` control message.

Stability: Experimental.
"""
from __future__ import annotations

import re

import numpy as np

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    parts = _SENTENCE.split(text.strip())
    return [p for p in parts if p]


def audio_to_pcm(samples: "np.ndarray") -> bytes:
    """float32 [-1, 1] -> 16-bit little-endian mono PCM bytes."""
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()
