#!/usr/bin/env python3
"""Verify KT002 Lua MISO text reception with a PING command.

Expected sequence:
    Lua putchar setup request 0x10
    -> setup reply 0x80010003
    -> Lua text report READY:KT002_FIXED_PDO
    -> Lua_MOSI PING request 0x1F
    -> Lua_MOSI ACK 0x80000000
    -> Lua text report containing PONG:KT002

The test filters periodic report types 0x01 and 0x02 and does not change PDO.
"""

from __future__ import annotations

import time

import usb.core

from drivers.kt002.protocol import extract_frames, pack_lua_mosi, pack_request
from drivers.kt002.transport import KT002USBTransport


LUA_PUTCHAR_SETUP_REQUEST = 0x10
LUA_TEXT_REPORT_TYPE = 0x10
SETUP_REPLY_HEADER = 0x80010003
LUA_MOSI_ACK_HEADER = 0x80000000
CALLER_ID = 1
TIMEOUT_SECONDS = 5.0
EXPECTED_TEXT = "PONG:KT002"


def receive_until(
    transport: KT002USBTransport,
    receive_buffer: bytearray,
    deadline: float,
):
    """Yield decoded frames until the absolute deadline."""
    while time.monotonic() < deadline:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        try:
            chunk = transport.read(timeout_ms=min(250, remaining_ms))
            receive_buffer.extend(chunk)
        except usb.core.USBTimeoutError:
            continue

        yield from extract_frames(receive_buffer)


def decode_lua_text(payload: bytes) -> str | None:
    """Decode a verified type-0x10 Lua text report."""
    if len(payload) < 4:
        return None

    header = int.from_bytes(payload[:4], "little")
    message_type = (header >> 8) & 0xFF
    if message_type != LUA_TEXT_REPORT_TYPE:
        return None

    return payload[4:].decode("utf-8", errors="replace")


def main() -> int:
    transport = KT002USBTransport()
    receive_buffer = bytearray()

    try:
        transport.connect()
        print(f"Connected: VID={transport.VID:04X} PID={transport.pid:04X}")
        transport.drain_input()

        setup_packet = pack_request(
            caller_id=CALLER_ID,
            request_type=LUA_PUTCHAR_SETUP_REQUEST,
        )
        transport.write(setup_packet)

        setup_ok = False
        ready_messages: list[str] = []
        setup_deadline = time.monotonic() + 2.0

        for reply in receive_until(transport, receive_buffer, setup_deadline):
            if reply.header == SETUP_REPLY_HEADER:
                setup_ok = True
                print(f"Setup ACK: 0x{reply.header:08X}")

            text = decode_lua_text(reply.payload)
            if text is not None:
                ready_messages.append(text)
                print(f"Lua MISO: {text.rstrip()}")

            if setup_ok and ready_messages:
                break

        if not setup_ok:
            print("FAIL: Lua putchar setup ACK was not received")
            return 1

        ping_packet = pack_lua_mosi(b"PING", caller_id=0)
        transport.write(ping_packet)

        ack_ok = False
        text_buffer = ""
        ping_deadline = time.monotonic() + TIMEOUT_SECONDS

        for reply in receive_until(transport, receive_buffer, ping_deadline):
            if reply.header == LUA_MOSI_ACK_HEADER:
                ack_ok = True
                print(f"Lua_MOSI ACK: 0x{reply.header:08X}")
                continue

            text = decode_lua_text(reply.payload)
            if text is None:
                continue

            text_buffer += text
            for line in text_buffer.splitlines():
                print(f"Lua MISO: {line}")

            if EXPECTED_TEXT in text_buffer:
                print(f"PASS: received {EXPECTED_TEXT}")
                return 0 if ack_ok else 1

        if not ack_ok:
            print("FAIL: Lua_MOSI ACK was not received")
        else:
            print(f"FAIL: {EXPECTED_TEXT} was not received before timeout")
        return 1

    finally:
        transport.close()
        print("KT002 USB connection closed")


if __name__ == "__main__":
    raise SystemExit(main())
