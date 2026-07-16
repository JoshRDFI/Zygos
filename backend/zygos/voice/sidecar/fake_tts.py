"""A scripted, dependency-free fake TTS worker.

Run as: python -m zygos.voice.sidecar.fake_tts <address>
It connects back to the runtime's listener and speaks the length-prefixed IPC
contract. Only the synthesis is fake; the process, transport, and protocol are real.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys

from zygos.voice.ipc import connect
from zygos.voice.sidecar.watch import CANCELLED, run_with_cancel_watch, safe_send_control

_SAMPLES_PER_CHAR = 80  # deterministic: PCM bytes per sentence = 2 * 80 * len(sentence)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def _pcm(sentence: str) -> bytes:
    return b"\x00\x00" * (_SAMPLES_PER_CHAR * max(1, len(sentence)))


async def _run(address: str) -> None:
    hold = os.environ.get("ZYGOS_FAKE_TTS_HOLD") == "1"
    conn = await connect(address)
    try:
        while True:
            try:
                kind, body = await conn.recv()
            except EOFError:
                return
            if kind != "control":
                continue
            mtype = body.get("type")
            if mtype == "synthesize":
                sentences = _sentences(body.get("text", "")) or [""]

                async def work(cancel_event):
                    if hold:
                        # Emit one chunk, then stay held until cancel/EOF.
                        await conn.send_pcm(_pcm(sentences[0]))
                        await cancel_event.wait()
                        return
                    for sentence in sentences:
                        if cancel_event.is_set():
                            return
                        await conn.send_pcm(_pcm(sentence))

                outcome = await run_with_cancel_watch(conn, work)
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
        raise SystemExit("usage: python -m zygos.voice.sidecar.fake_tts <address>")
    asyncio.run(_run(sys.argv[1]))


if __name__ == "__main__":
    main()
