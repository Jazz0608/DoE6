#!/usr/bin/env python3
"""Safe KT002 direct-USB ping probe.

Derived from the official ShizukuProtocol.dll framing and USB setup:
  USB interface 0, bulk OUT 0x01, bulk IN 0x81
  frame = A5 + uint32_le(payload_len) + payload + xor(payload) + 5A
  request payload header = (caller_id << 16) | (request_type << 8) | 1

This script sends only protocol request type 0x08 (PING). It does not trigger PD,
change VBUS, execute Lua, or require a charger/load.
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
PING_REQUEST_TYPE = 0x08
REQUEST_MARKER = 0x01


def xor8(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value


def make_frame(payload: bytes) -> bytes:
    return b"\xA5" + struct.pack("<I", len(payload)) + payload + bytes((xor8(payload), 0x5A))


def make_request(caller_id: int, request_type: int, arguments: tuple[int, ...] = ()) -> bytes:
    if not 0 <= caller_id <= 0xFFFF:
        raise ValueError("caller_id must be 0..65535")
    header = (caller_id << 16) | ((request_type & 0xFF) << 8) | REQUEST_MARKER
    payload = struct.pack("<I", header)
    if arguments:
        payload += struct.pack("<" + "I" * len(arguments), *arguments)
    return make_frame(payload)


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
        if payload_len > 4096:
            del buffer[0]
            continue
        total = payload_len + 7
        if len(buffer) < total:
            break
        raw = bytes(buffer[:total])
        del buffer[:total]
        payload = raw[5:5 + payload_len]
        valid = raw[-1] == 0x5A and raw[-2] == xor8(payload)
        frames.append((raw, payload, valid))
    return frames


def find_kt002():
    for pid in VALID_PIDS:
        dev = usb.core.find(idVendor=VID, idProduct=pid)
        if dev is not None:
            return dev, pid
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description="KT002 direct USB safe ping test")
    parser.add_argument("--caller-id", type=lambda x: int(x, 0), default=0,
                        help="16-bit caller ID, default 0")
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="response timeout in seconds, default 3")
    args = parser.parse_args()

    dev, pid = find_kt002()
    if dev is None:
        print("ERROR: KT002 not found (VID 0483, PID FFFF/FFFE/374B).")
        return 2

    print(f"KT002 found: VID=0483 PID={pid:04X}")
    detached = False
    claimed = False

    try:
        try:
            if dev.is_kernel_driver_active(INTERFACE):
                dev.detach_kernel_driver(INTERFACE)
                detached = True
                print("Detached Linux kernel driver from interface 0.")
        except (NotImplementedError, usb.core.USBError):
            pass

        # 不重新設定整台複合 USB 裝置
        # dev.set_configuration()
        usb.util.claim_interface(dev, INTERFACE)
        claimed = True

        # Clear any prior endpoint halt and stale input packets.
        for ep in (EP_OUT, EP_IN):
            try:
                dev.clear_halt(ep)
            except usb.core.USBError:
                pass
        while True:
            try:
                dev.read(EP_IN, 4096, timeout=50)
            except usb.core.USBTimeoutError:
                break

        request = make_request(args.caller_id, PING_REQUEST_TYPE)
        print("TX:", request.hex(" ").upper())
        written = dev.write(EP_OUT, request, timeout=2000)
        print(f"TX bytes: {written}")

        deadline = time.monotonic() + args.timeout
        rx_buffer = bytearray()
        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            try:
                chunk = bytes(dev.read(EP_IN, 4096, timeout=min(250, remaining_ms)))
                rx_buffer.extend(chunk)
            except usb.core.USBTimeoutError:
                continue

            for raw, payload, valid in extract_frames(rx_buffer):
                print("RX:", raw.hex(" ").upper())
                print("Frame valid:", valid)
                if len(payload) >= 4:
                    header = struct.unpack_from("<I", payload, 0)[0]
                    caller = (header >> 16) & 0xFFFF
                    message_type = (header >> 8) & 0xFF
                    reply_code = header & 0xFF
                    print(f"Header=0x{header:08X} caller={caller} "
                          f"message_type=0x{message_type:02X} reply_code=0x{reply_code:02X}")
                if valid:
                    print("PASS: KT002 returned a valid Shizuku protocol frame.")
                    return 0

        print("FAIL: no valid Shizuku reply before timeout.")
        return 1

    except usb.core.USBError as exc:
        print(f"USB ERROR: {exc}")
        print("Run with sudo, and ensure KT Toolbox is not connected to the KT002.")
        return 3
    finally:
        if claimed:
            try:
                usb.util.release_interface(dev, INTERFACE)
            except usb.core.USBError:
                pass
        usb.util.dispose_resources(dev)
        if detached:
            try:
                dev.attach_kernel_driver(INTERFACE)
            except (NotImplementedError, usb.core.USBError):
                pass


if __name__ == "__main__":
    sys.exit(main())
