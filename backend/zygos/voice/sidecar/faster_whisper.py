"""Real STT worker backed by faster-whisper (CTranslate2), CPU-first.

Run as: python -m zygos.voice.sidecar.faster_whisper <address>
Speaks the same length-prefixed IPC contract as fake_stt. Only the inference is
real. faster_whisper is imported lazily so the module is importable (for the pure
helpers) without the optional `voice` extra installed.

Transcription is final-only: PCM is buffered between `start` and `end`, then the
whole utterance is transcribed once and a single `final` is emitted.

Stability: Experimental.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys

import numpy as np

from zygos.voice.ipc import connect

_WS = re.compile(r"\s+")


def pcm_to_audio(buf: bytes) -> "np.ndarray":
    """16-bit little-endian mono PCM -> float32 in [-1, 1] at 16 kHz."""
    return np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0


def join_segments(segments) -> str:
    """Concatenate segment texts, collapse whitespace, strip."""
    return _WS.sub(" ", " ".join(s.text for s in segments)).strip()


def _load_model():
    from faster_whisper import WhisperModel  # lazy: optional `voice` extra

    model = os.environ.get("ZYGOS_STT_MODEL", "base.en")
    device = os.environ.get("ZYGOS_STT_DEVICE", "cpu")
    compute_type = os.environ.get("ZYGOS_STT_COMPUTE_TYPE", "int8")
    download_root = os.environ.get("ZYGOS_STT_DOWNLOAD_ROOT") or None
    return WhisperModel(model, device=device, compute_type=compute_type,
                        download_root=download_root)


def _transcribe(model, audio: "np.ndarray") -> str:
    segments, _info = model.transcribe(audio, language="en", beam_size=1)
    return join_segments(segments)


async def _run(address: str) -> None:
    conn = await connect(address)
    model = None            # loaded once below, after connect()
    buffer = bytearray()
    active = False
    try:
        model = await asyncio.to_thread(_load_model)  # heavy; off the event loop
        while True:
            try:
                kind, body = await conn.recv()
            except EOFError:
                return
            if kind == "pcm":
                if active:
                    buffer.extend(body)
                continue
            mtype = body.get("type")
            if mtype == "start":
                active, buffer = True, bytearray()
            elif mtype == "end":
                if active:
                    active = False
                    try:
                        audio = pcm_to_audio(bytes(buffer))
                        text = await asyncio.to_thread(_transcribe, model, audio)
                        await conn.send_control({"type": "final", "text": text})
                    except Exception as exc:  # noqa: BLE001 - report, don't crash
                        await conn.send_control({"type": "error", "message": str(exc)})
            elif mtype == "cancel":
                active, buffer = False, bytearray()
            elif mtype == "health":
                await conn.send_control({"type": "health_ok"})
    finally:
        await conn.close()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m zygos.voice.sidecar.faster_whisper <address>")
    asyncio.run(_run(sys.argv[1]))


if __name__ == "__main__":
    main()
