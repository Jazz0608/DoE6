#!/usr/bin/env python3
"""KT002 direct-USB Lua_MOSI communication test.

Purpose:
    Send a harmless ASCII message to the KT002 Lua input channel by using the
    official Shizuku protocol request ID 0x1F (Lua_MOSI).

This test does not execute Lua, trigger USB-PD, or change VBUS voltage.
A Lua program that consumes the Lua MOSI channel must already be running on the
KT002, for example through onBoot.lua.

Protocol facts recovered from ShizukuProtocol.dll:
    USB interface : 0
    Bulk OUT       : 0x01
    Bulk IN        : 0x81
    Frame          : A5 + uint32_le(payload length) + payload + XOR + 5A
    Request header : (caller_id << 16) | (request_type << 8) | 0x01
    Lua_MOSI       : request type 0x1F
    First argument : content_length << 16
    Following bytes are copied into the UInt32 argument buffer at byte offset 4.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time

import usb.core
import usb.util

VID = 0x0483
VALID_PIDS = (0xFFFF, 0xFFFE, 0x374B)
INTERFACE = 0
EP_OUT = 0x01
EP_IN = 0x81

REQUEST_MARKER = 0x01
LUA_MOSI_REQUEST_TYPE = 0x1F
MAX_FRAME_PAYLOAD = 4096


def xor8(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value


def make_frame(payload: bytes) -> bytes:
    return (
        b"\xA5"
        + struct.pack("<I", len(payload))
        + payload
        + bytes((xor8(payload), 0x5A))
    )


def make_request(caller_id: int, request_type: int, arguments: bytes) -> bytes:
    if not 0 <= caller_id <= 0xFFFF:
        raise ValueError("caller_id must be within 0..65535")

    header = (
        (caller_id << 16)
        | ((request_type & 0xFF) << 8)
        | REQUEST_MARKER
    )
    return make_frame(struct.pack("<I", header) + arguments)


def make_lua_mosi_request(content: bytes, caller_id: int = 0) -> bytes:
    """Build the exact Lua_MOSI argument layout used by the official DLL."""
    if not content:
        raise ValueError("content must not be empty")
    if len(content) > 0xFFFF:
        raise ValueError("content is too long for Lua_MOSI")

    # DLL allocation: ((len(content) + 3) // 4 + 4) UInt32 values.
    # UInt32[0] contains len(content) << 16. Content starts at byte offset 4.
    uint32_count = ((len(content) + 3) // 4) + 4
    arguments = bytearray(uint32_count * 4)
    struct.pack_into("<I", arguments, 0, len(content) << 16)
    arguments[4:4 + len(content)] = content

    return make_request(caller_id, LUA_MOSI_REQUEST_TYPE, bytes(arguments))


def extract_frames(buffer: bytearray):
    frames = []

    while True:
        try:
            start = buffer.index(0xA5)
        except ValueError:
            buffer.clear()
            break

        if start:
            del buffer[:start]

        if len(buffer) < 7:
            break

        payload_len = struct.unpack_from("<I", buffer, 1)[0]
        if payload_len > MAX_FRAME_PAYLOAD:
            del buffer[0]
            continue

        total_len = payload_len + 7
        if len(buffer) < total_len:
            break

        raw = bytes(buffer[:total_len])
        del buffer[:total_len]

        payload = raw[5:5 + payload_len]
        valid = raw[-1] == 0x5A and raw[-2] == xor8(payload)
        frames.append((raw, payload, valid))

    return frames


def find_kt002():
    for pid in VALID_PIDS:
        device = usb.core.find(idVendor=VID, idProduct=pid)
        if device is not None:
            return device, pid
    return None, None


def decode_header(payload: bytes) -> None:
    if len(payload) < 4:
        print("RX payload is shorter than four bytes.")
        return

    header = struct.unpack_from("<I", payload, 0)[0]
    caller = (header >> 16) & 0xFFFF
    message_type = (header >> 8) & 0xFF
    low_byte = header & 0xFF

    print(
        f"Header=0x{header:08X} caller={caller} "
        f"message_type=0x{message_type:02X} low_byte=0x{low_byte:02X}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a harmless message to KT002 Lua_MOSI over direct USB"
    )
    parser.add_argument(
        "message",
        nargs="?",
        default="HELLO",
        help="ASCII/UTF-8 text to send, default: HELLO",
    )
    parser.add_argument(
        "--caller-id",
        type=lambda value: int(value, 0),
        default=0,
        help="16-bit caller ID, default: 0",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="reply timeout in seconds, default: 3",
    )
    args = parser.parse_args()

    content = args.message.encode("utf-8")
    device, pid = find_kt002()

    if device is None:
        print("ERROR: KT002 not found (VID 0483, PID FFFF/FFFE/374B).")
        return 2

    print(f"KT002 found: VID=0483 PID={pid:04X}")
    print(f"Lua_MOSI text: {args.message!r}")
    print(f"Lua_MOSI bytes: {len(content)}")

    detached = False
    claimed = False

    try:
        try:
            if device.is_kernel_driver_active(INTERFACE):
                device.detach_kernel_driver(INTERFACE)
                detached = True
                print("Detached Linux kernel driver from interface 0.")
        except (NotImplementedError, usb.core.USBError):
            pass

        # Do not call set_configuration(). KT002 is a composite USB device and
        # changing its active configuration can return Errno 16 Resource busy.
        usb.util.claim_interface(device, INTERFACE)
        claimed = True

        for endpoint in (EP_OUT, EP_IN):
            try:
                device.clear_halt(endpoint)
            except usb.core.USBError:
                pass

        # Drain stale packets before sending the request.
        while True:
            try:
                device.read(EP_IN, 4096, timeout=50)
            except usb.core.USBTimeoutError:
                break

        request = make_lua_mosi_request(content, args.caller_id)
        print("TX:", request.hex(" ").upper())

        written = device.write(EP_OUT, request, timeout=2000)
        print(f"TX bytes: {written}")

        deadline = time.monotonic() + args.timeout
        receive_buffer = bytearray()

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            try:
                chunk = bytes(
                    device.read(
                        EP_IN,
                        4096,
                        timeout=min(250, remaining_ms),
                    )
                )
                receive_buffer.extend(chunk)
            except usb.core.USBTimeoutError:
                continue

            for raw, payload, valid in extract_frames(receive_buffer):
                print("RX:", raw.hex(" ").upper())
                print("Frame valid:", valid)
                decode_header(payload)

                if valid:
                    print("PASS: KT002 acknowledged the Lua_MOSI request.")
                    print(
                        "Next check: verify that the running onBoot.lua "
                        "actually received the text."
                    )
                    return 0

        print("FAIL: no valid Shizuku reply before timeout.")
        print(
            "Check that KT002 is in application mode and that no other "
            "program is using interface 0."
        )
        return 1

    except usb.core.USBError as exc:
        print(f"USB ERROR: {exc}")
        print("Run with sudo and make sure KT Toolbox is not connected.")
        return 3
    finally:
        if claimed:
            try:
                usb.util.release_interface(device, INTERFACE)
            except usb.core.USBError:
                pass

        usb.util.dispose_resources(device)

        if detached:
            try:
                device.attach_kernel_driver(INTERFACE)
            except (NotImplementedError, usb.core.USBError):
                pass


if __name__ == "__main__":
    sys.exit(main())
