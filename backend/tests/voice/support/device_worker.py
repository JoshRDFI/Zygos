"""Test fixture: a TTS-shaped worker whose health_ok reports a device from env.

Run as: python .../device_worker.py <address>
ZYGOS_TEST_DEVICE / ZYGOS_TEST_REASON set the reported device / reason.
"""
import asyncio
import os
import sys

from zygos.voice.ipc import connect


async def _run(address: str) -> None:
    conn = await connect(address)
    try:
        while True:
            try:
                kind, body = await conn.recv()
            except EOFError:
                return
            if kind == "control" and body.get("type") == "health":
                reply = {"type": "health_ok", "device": os.environ.get("ZYGOS_TEST_DEVICE", "cpu")}
                if os.environ.get("ZYGOS_TEST_REASON"):
                    reply["reason"] = os.environ["ZYGOS_TEST_REASON"]
                await conn.send_control(reply)
    finally:
        await conn.close()


asyncio.run(_run(sys.argv[1]))
