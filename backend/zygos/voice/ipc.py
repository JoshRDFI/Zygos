from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import uuid
from typing import Iterator

from zygos.voice.errors import IpcProtocolError

KIND_CONTROL = 0x00
KIND_PCM = 0x01
_HEADER = 4
MAX_FRAME_BYTES = 8 * 1024 * 1024  # 8 MiB ceiling per frame


def encode_frame(kind: int, body: bytes) -> bytes:
    payload = bytes([kind]) + body
    return len(payload).to_bytes(_HEADER, "big") + payload


class FrameDecoder:
    """Incremental length-prefixed frame parser."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> None:
        self._buf.extend(data)

    def frames(self) -> Iterator[tuple[int, bytes]]:
        while True:
            if len(self._buf) < _HEADER:
                return
            size = int.from_bytes(self._buf[:_HEADER], "big")
            if size < 1:
                raise IpcProtocolError("frame length underflow")
            if size > MAX_FRAME_BYTES:
                raise IpcProtocolError(f"frame length {size} exceeds cap")
            if len(self._buf) < _HEADER + size:
                return
            payload = bytes(self._buf[_HEADER : _HEADER + size])
            del self._buf[: _HEADER + size]
            yield payload[0], payload[1:]


class IpcConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._decoder = FrameDecoder()
        self._pending: list[tuple[int, bytes]] = []
        self._write_lock = asyncio.Lock()

    async def send_control(self, msg: dict) -> None:
        await self._send(KIND_CONTROL, json.dumps(msg).encode())

    async def send_pcm(self, pcm: bytes) -> None:
        await self._send(KIND_PCM, pcm)

    async def _send(self, kind: int, body: bytes) -> None:
        async with self._write_lock:
            self._writer.write(encode_frame(kind, body))
            await self._writer.drain()  # backpressure

    async def recv(self) -> tuple[str, dict | bytes]:
        while not self._pending:
            chunk = await self._reader.read(65536)
            if not chunk:
                raise EOFError("sidecar connection closed")
            self._decoder.feed(chunk)
            self._pending.extend(self._decoder.frames())
        kind, body = self._pending.pop(0)
        if kind == KIND_CONTROL:
            try:
                data = json.loads(body)
            except ValueError as exc:  # noqa: TRY003
                raise IpcProtocolError("bad control JSON") from exc
            if not isinstance(data, dict):
                raise IpcProtocolError("control frame not an object")
            return "control", data
        return "pcm", body

    async def close(self) -> None:
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except (OSError, RuntimeError):  # pragma: no cover
            pass


class Listener:
    def __init__(self, server: asyncio.AbstractServer, address: str, uds_path: str | None) -> None:
        self._server = server
        self.address = address
        self._uds_path = uds_path
        self._accepted: asyncio.Queue[IpcConnection] = asyncio.Queue()

    def _on_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._accepted.put_nowait(IpcConnection(reader, writer))

    async def accept(self) -> IpcConnection:
        return await self._accepted.get()

    async def close(self) -> None:
        self._server.close()
        await self._server.wait_closed()
        if self._uds_path and os.path.exists(self._uds_path):
            os.unlink(self._uds_path)


async def listen() -> Listener:
    holder: dict[str, Listener] = {}

    def handler(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        holder["l"]._on_client(r, w)

    if sys.platform != "win32" and hasattr(asyncio, "start_unix_server"):
        path = os.path.join(tempfile.gettempdir(), f"zygos-voice-{uuid.uuid4().hex}.sock")
        server = await asyncio.start_unix_server(handler, path=path)
        listener = Listener(server, path, path)
    else:
        server = await asyncio.start_server(handler, host="127.0.0.1", port=0)
        sock = server.sockets[0].getsockname()
        listener = Listener(server, f"{sock[0]}:{sock[1]}", None)
    holder["l"] = listener
    return listener


async def connect(address: str) -> IpcConnection:
    if ":" in address and not os.path.sep in address:
        host, port = address.rsplit(":", 1)
        reader, writer = await asyncio.open_connection(host, int(port))
    else:
        reader, writer = await asyncio.open_unix_connection(path=address)
    return IpcConnection(reader, writer)
