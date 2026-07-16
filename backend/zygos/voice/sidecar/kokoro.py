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

import asyncio
import os
import re
import sys

import numpy as np

from zygos.voice.ipc import connect
from zygos.voice.kokoro_assets import ensure_assets
from zygos.voice.sidecar.watch import CANCELLED, run_with_cancel_watch, safe_send_control

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    parts = _SENTENCE.split(text.strip())
    return [p for p in parts if p]


def audio_to_pcm(samples: "np.ndarray") -> bytes:
    """float32 [-1, 1] -> 16-bit little-endian mono PCM bytes."""
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def _load_kokoro():
    from kokoro_onnx import Kokoro  # lazy: optional `voice` extra

    onnx_path, voices_path = ensure_assets(os.environ.get("ZYGOS_TTS_DOWNLOAD_ROOT") or None)
    return Kokoro(str(onnx_path), str(voices_path))


def _synthesize(kokoro, sentence: str, voice: str, lang: str) -> "np.ndarray":
    samples, _rate = kokoro.create(sentence, voice, is_phonemes=False, lang=lang)
    return samples


async def _run(address: str) -> None:
    conn = await connect(address)
    voice = os.environ.get("ZYGOS_TTS_VOICE", "af_heart")
    lang = os.environ.get("ZYGOS_TTS_LANG", "en-us")
    kokoro = None
    try:
        kokoro = await asyncio.to_thread(_load_kokoro)
        while True:
            try:
                kind, body = await conn.recv()
            except EOFError:
                return
            if kind != "control":
                continue
            mtype = body.get("type")
            if mtype == "synthesize":
                text = body.get("text", "")

                async def work(cancel_event):
                    for sentence in split_sentences(text):
                        if cancel_event.is_set():
                            return
                        samples = await asyncio.to_thread(
                            _synthesize, kokoro, sentence, voice, lang)
                        if cancel_event.is_set():
                            return
                        await conn.send_pcm(audio_to_pcm(samples))

                try:
                    outcome = await run_with_cancel_watch(conn, work)
                except Exception as exc:  # noqa: BLE001 - report, don't crash
                    await safe_send_control(conn, {"type": "error", "message": str(exc)})
                else:
                    terminal = "cancelled" if outcome == CANCELLED else "end"
                    await safe_send_control(conn, {"type": terminal})
            elif mtype == "cancel":
                pass  # no active utterance to interrupt; ignore late cancel
            elif mtype == "health":
                await conn.send_control({"type": "health_ok"})
    finally:
        await conn.close()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m zygos.voice.sidecar.kokoro <address>")
    asyncio.run(_run(sys.argv[1]))


if __name__ == "__main__":
    main()
