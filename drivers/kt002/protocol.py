"""Shizuku protocol encoding and decoding for the POWER-Z KT002.

This module contains pure protocol operations only. It does not search for USB
devices, claim USB interfaces, access USB endpoints, or control USB-PD.
"""

from __future__ import annotations

import struct

from drivers.kt002.constants import (
    SHIZUKU_FRAME_END,
    SHIZUKU_FRAME_START,
    SHIZUKU_MAX_PAYLOAD_SIZE,
    SHIZUKU_REQUEST_LUA_MOSI,
    SHIZUKU_REQUEST_MARKER,
)
from drivers.kt002.exceptions import KT002ProtocolError
from drivers.kt002.models import KT002Reply


SHIZUKU_FRAME_OVERHEAD = 7
SHIZUKU_HEADER_SIZE = 4
LUA_MOSI_MAX_CONTENT_SIZE = 0xFFFF


def xor8(data: bytes) -> int:
    """Return the 8-bit XOR of all supplied bytes."""
    value = 0
    for byte in data:
        value ^= byte
    return value


def pack_frame(payload: bytes) -> bytes:
    """Wrap a payload in the verified Shizuku outer frame."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("payload must be bytes-like")

    payload_bytes = bytes(payload)
    if len(payload_bytes) > SHIZUKU_MAX_PAYLOAD_SIZE:
        raise ValueError(
            f"payload exceeds {SHIZUKU_MAX_PAYLOAD_SIZE} bytes"
        )

    return (
        bytes((SHIZUKU_FRAME_START,))
        + struct.pack("<I", len(payload_bytes))
        + payload_bytes
        + bytes((xor8(payload_bytes), SHIZUKU_FRAME_END))
    )


def pack_request_header(
    caller_id: int,
    request_type: int,
    request_marker: int = SHIZUKU_REQUEST_MARKER,
) -> int:
    """Encode the 32-bit Shizuku request header."""
    if not isinstance(caller_id, int):
        raise TypeError("caller_id must be an integer")
    if not isinstance(request_type, int):
        raise TypeError("request_type must be an integer")
    if not isinstance(request_marker, int):
        raise TypeError("request_marker must be an integer")

    if not 0 <= caller_id <= 0xFFFF:
        raise ValueError("caller_id must be within 0..65535")
    if not 0 <= request_type <= 0xFF:
        raise ValueError("request_type must be within 0..255")
    if not 0 <= request_marker <= 0xFF:
        raise ValueError("request_marker must be within 0..255")

    return (
        (caller_id << 16)
        | (request_type << 8)
        | request_marker
    )


def pack_request(
    caller_id: int,
    request_type: int,
    arguments: bytes = b"",
) -> bytes:
    """Build a complete Shizuku request packet."""
    if not isinstance(arguments, (bytes, bytearray, memoryview)):
        raise TypeError("arguments must be bytes-like")

    header = pack_request_header(
        caller_id=caller_id,
        request_type=request_type,
    )
    payload = struct.pack("<I", header) + bytes(arguments)
    return pack_frame(payload)


def pack_lua_mosi(
    content: bytes,
    caller_id: int = 0,
) -> bytes:
    """Build a Lua_MOSI request using the official argument layout."""
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise TypeError("Lua_MOSI content must be bytes-like")

    content_bytes = bytes(content)
    if not content_bytes:
        raise ValueError("Lua_MOSI content must not be empty")
    if len(content_bytes) > LUA_MOSI_MAX_CONTENT_SIZE:
        raise ValueError("Lua_MOSI content exceeds 65535 bytes")

    uint32_count = ((len(content_bytes) + 3) // 4) + 4
    arguments = bytearray(uint32_count * 4)
    struct.pack_into("<I", arguments, 0, len(content_bytes) << 16)
    arguments[4:4 + len(content_bytes)] = content_bytes

    return pack_request(
        caller_id=caller_id,
        request_type=SHIZUKU_REQUEST_LUA_MOSI,
        arguments=bytes(arguments),
    )


def decode_reply(raw_frame: bytes) -> KT002Reply:
    """Validate and decode exactly one complete Shizuku reply frame."""
    if not isinstance(raw_frame, (bytes, bytearray, memoryview)):
        raise TypeError("raw_frame must be bytes-like")

    raw = bytes(raw_frame)
    if len(raw) < SHIZUKU_FRAME_OVERHEAD:
        raise KT002ProtocolError(
            f"KT002 frame is shorter than {SHIZUKU_FRAME_OVERHEAD} bytes"
        )
    if raw[0] != SHIZUKU_FRAME_START:
        raise KT002ProtocolError("invalid KT002 frame start byte")

    payload_length = struct.unpack_from("<I", raw, 1)[0]
    if payload_length > SHIZUKU_MAX_PAYLOAD_SIZE:
        raise KT002ProtocolError(
            f"KT002 frame payload exceeds {SHIZUKU_MAX_PAYLOAD_SIZE} bytes"
        )

    expected_frame_length = payload_length + SHIZUKU_FRAME_OVERHEAD
    if len(raw) != expected_frame_length:
        raise KT002ProtocolError(
            "invalid KT002 frame length: "
            f"expected {expected_frame_length}, received {len(raw)}"
        )
    if raw[-1] != SHIZUKU_FRAME_END:
        raise KT002ProtocolError("invalid KT002 frame terminator")

    payload = raw[5:5 + payload_length]
    expected_xor = xor8(payload)
    received_xor = raw[-2]
    if received_xor != expected_xor:
        raise KT002ProtocolError(
            "invalid KT002 frame XOR: "
            f"expected 0x{expected_xor:02X}, received 0x{received_xor:02X}"
        )
    if len(payload) < SHIZUKU_HEADER_SIZE:
        raise KT002ProtocolError(
            "KT002 reply payload is shorter than 4 bytes"
        )

    header = struct.unpack_from("<I", payload, 0)[0]
    return KT002Reply(
        raw=raw,
        payload=payload,
        header=header,
        caller_id=(header >> 16) & 0xFFFF,
        message_type=(header >> 8) & 0xFF,
        low_byte=header & 0xFF,
    )


def extract_frames(buffer: bytearray) -> list[KT002Reply]:
    """Extract and decode every complete Shizuku frame in a buffer.

    Partial data remains in the supplied bytearray for the next USB read.
    Bytes before the next frame-start candidate are discarded.
    """
    if not isinstance(buffer, bytearray):
        raise TypeError("buffer must be a bytearray")

    replies: list[KT002Reply] = []

    while True:
        try:
            frame_start = buffer.index(SHIZUKU_FRAME_START)
        except ValueError:
            buffer.clear()
            break

        if frame_start:
            del buffer[:frame_start]

        if len(buffer) < SHIZUKU_FRAME_OVERHEAD:
            break

        payload_length = struct.unpack_from("<I", buffer, 1)[0]
        if payload_length > SHIZUKU_MAX_PAYLOAD_SIZE:
            del buffer[0]
            continue

        frame_length = payload_length + SHIZUKU_FRAME_OVERHEAD
        if len(buffer) < frame_length:
            break

        raw_frame = bytes(buffer[:frame_length])
        del buffer[:frame_length]
        replies.append(decode_reply(raw_frame))

    return replies


__all__ = [
    "SHIZUKU_FRAME_OVERHEAD",
    "SHIZUKU_HEADER_SIZE",
    "LUA_MOSI_MAX_CONTENT_SIZE",
    "xor8",
    "pack_frame",
    "pack_request_header",
    "pack_request",
    "pack_lua_mosi",
    "decode_reply",
    "extract_frames",
]
