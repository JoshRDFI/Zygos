"""A scripted, dependency-free fake STT worker.

Run as: python -m zygos.voice.sidecar.fake_stt <address>
It connects back to the runtime's listener and speaks the length-prefixed IPC
contract. Only the inference is fake; the process, transport, and protocol are real.
"""
from __future__ import annotations

import asyncio
import os
import sys

from zygos.voice.ipc import connect


async def _run(address: str) -> None:
    transcript = os.environ.get("ZYGOS_FAKE_STT_TRANSCRIPT", "hello world")
    conn = await connect(address)
    received = 0
    active = False
    try:
        while True:
            try:
                kind, body = await conn.recv()
            except EOFError:
                return
            if kind == "pcm":
                if active:
                    received += len(body)
                    # emit a coarse interim result every ~1 KiB of audio
                    words = transcript.split()
                    n = min(len(words), 1 + received // 1024)
                    await conn.send_control({"type": "partial", "text": " ".join(words[:n])})
                continue
            mtype = body.get("type")
            if mtype == "start":
                active, received = True, 0
            elif mtype == "end":
                if active:
                    await conn.send_control({"type": "final", "text": transcript})
                active = False
            elif mtype == "cancel":
                active, received = False, 0
            elif mtype == "health":
                await conn.send_control({"type": "health_ok"})
    finally:
        await conn.close()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m zygos.voice.sidecar.fake_stt <address>")
    asyncio.run(_run(sys.argv[1]))


if __name__ == "__main__":
    main()
