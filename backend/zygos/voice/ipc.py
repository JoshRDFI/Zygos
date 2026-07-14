from __future__ import annotations

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
