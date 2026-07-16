"""Unit tests for the consumer drain-to-terminal helper."""
from __future__ import annotations

import asyncio

from zygos.voice.ipc import connect, listen
from zygos.voice.plugin import _drain_to_terminal


async def _pair():
    listener = await listen()
    client = await connect(listener.address)
    server = await listener.accept()
    return listener, server, client


async def test_drains_pcm_and_partial_then_stops_at_terminal():
    listener, server, client = await _pair()
    try:
        await server.send_pcm(b"\x00\x00")
        await server.send_control({"type": "partial", "text": "x"})
        await server.send_pcm(b"\x01\x01")
        await server.send_control({"type": "cancelled"})
        await server.send_control({"type": "final", "text": "next-utterance"})

        await _drain_to_terminal(client)

        # The terminal was consumed; the NEXT utterance's frame remains.
        kind, body = await client.recv()
        assert kind == "control" and body == {"type": "final", "text": "next-utterance"}
    finally:
        await client.close()
        await server.close()
        await listener.close()


async def test_stops_at_end_terminal():
    listener, server, client = await _pair()
    try:
        await server.send_control({"type": "end"})
        await server.send_control({"type": "sentinel-after"})
        await _drain_to_terminal(client)
        kind, body = await client.recv()
        assert body == {"type": "sentinel-after"}
    finally:
        await client.close()
        await server.close()
        await listener.close()


async def test_returns_on_eof():
    listener, server, client = await _pair()
    try:
        await server.close()  # EOF, no terminal ever arrives
        await asyncio.wait_for(_drain_to_terminal(client), timeout=1.0)
    finally:
        await client.close()
        await listener.close()


async def test_returns_within_budget_when_silent():
    listener, server, client = await _pair()
    try:
        # No frames and no EOF: must give up within ~budget_s, not hang.
        await asyncio.wait_for(
            _drain_to_terminal(client, poll_s=0.02, budget_s=0.2), timeout=1.0)
    finally:
        await client.close()
        await server.close()
        await listener.close()
