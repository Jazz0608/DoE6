#!/usr/bin/env python3
"""Phase 2 raw Lua MISO probe for the KT002.

Safe test sequence:
    1. Register Lua putchar reports with request type 0x10 and caller ID 1.
    2. Send the already verified Lua_MOSI PING request.
    3. Capture and print every returned Shizuku frame for five seconds.

This test does not request a PDO or change VBUS.
"""

from __future__ import annotations

import time

import usb.core

from drivers.kt002.constants import (
    SHIZUKU_REQUEST_LUA_MOSI,
)
from drivers.kt002.protocol import (
    extract_frames,
    pack_lua_mosi,
    pack_request,
)
from drivers.kt002.transport import KT002USBTransport


LUA_PUTCHAR_SETUP_REQUEST = 0x10
CALLBACK_CALLER_ID = 1
CAPTURE_SECONDS = 5.0


def printable_payload(payload: bytes) -> str:
    """Return a conservative ASCII view of bytes after the 4-byte header."""
    data = payload[4:]
    return "".join(chr(value) if 32 <= value <= 126 else "." for value in data)


def read_frames(
    transport: KT002USBTransport,
    receive_buffer: bytearray,
    duration: float,
):
    """Yield all valid Shizuku replies received during one capture window."""
    deadline = time.monotonic() + duration

    while time.monotonic() < deadline:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        try:
            chunk = transport.read(timeout_ms=min(250, remaining_ms))
            receive_buffer.extend(chunk)
        except usb.core.USBTimeoutError:
            continue

        for reply in extract_frames(receive_buffer):
            yield reply


def print_reply(label: str, reply) -> None:
    print(f"{label} RAW: {reply.raw.hex(' ').upper()}")
    print(f"{label} HEADER: 0x{reply.header:08X}")
    print(f"{label} CALLER: 0x{reply.caller_id:04X}")
    print(f"{label} TYPE: 0x{reply.message_type:02X}")
    print(f"{label} LOW: 0x{reply.low_byte:02X}")
    print(f"{label} PAYLOAD: {reply.payload.hex(' ').upper()}")
    print(f"{label} ASCII_AFTER_HEADER: {printable_payload(reply.payload)!r}")


def main() -> int:
    transport = KT002USBTransport()
    receive_buffer = bytearray()

    try:
        transport.connect()
        print(f"Connected: VID={transport.VID:04X} PID={transport.pid:04X}")

        transport.drain_input()

        setup_packet = pack_request(
            caller_id=CALLBACK_CALLER_ID,
            request_type=LUA_PUTCHAR_SETUP_REQUEST,
        )
        print("SETUP TX:", setup_packet.hex(" ").upper())
        transport.write(setup_packet)

        setup_replies = list(read_frames(transport, receive_buffer, 2.0))
        if not setup_replies:
            print("FAIL: no reply to LuaPutCharHandler_Setup request")
            return 1

        for index, reply in enumerate(setup_replies, start=1):
            print_reply(f"SETUP RX {index}", reply)

        ping_packet = pack_lua_mosi(b"PING", caller_id=0)
        print("PING TX:", ping_packet.hex(" ").upper())
        transport.write(ping_packet)

        captured = []
        for reply in read_frames(
            transport,
            receive_buffer,
            CAPTURE_SECONDS,
        ):
            captured.append(reply)
            print_reply(f"PING RX {len(captured)}", reply)

        if not captured:
            print("FAIL: no frames captured after PING")
            return 1

        print(f"PASS: captured {len(captured)} frame(s) after PING")
        print("Check whether any payload contains PONG:KT002 or character data.")
        return 0

    finally:
        transport.close()
        print("KT002 USB connection closed")


if __name__ == "__main__":
    raise SystemExit(main())
