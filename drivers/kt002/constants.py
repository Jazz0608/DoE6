"""
Constants for the POWER-Z KT002 direct-USB driver.

The USB parameters and Shizuku protocol values in this module were
recovered from the official ShizukuProtocol.dll and verified with
the KT002 connected directly to a Raspberry Pi.

This module contains constants only. It must not perform USB access,
protocol operations, Lua communication, or PDO control.
"""

from __future__ import annotations


# ------------------------------------------------------------------
# USB device identification
# ------------------------------------------------------------------

KT002_USB_VID = 0x0483

KT002_USB_PIDS = (
    0xFFFF,
    0xFFFE,
    0x374B,
)


# ------------------------------------------------------------------
# USB interface and endpoints
# ------------------------------------------------------------------

KT002_USB_INTERFACE = 0

KT002_USB_EP_OUT = 0x01

KT002_USB_EP_IN = 0x81

KT002_USB_READ_SIZE = 4096


# ------------------------------------------------------------------
# Shizuku outer frame
#
# Frame:
#     0xA5
#     Payload length, UInt32 little-endian
#     Payload
#     Payload XOR
#     0x5A
# ------------------------------------------------------------------

SHIZUKU_FRAME_START = 0xA5

SHIZUKU_FRAME_END = 0x5A

SHIZUKU_MAX_PAYLOAD_SIZE = 4096


# ------------------------------------------------------------------
# Shizuku request header
#
# Request header:
#     caller_id << 16
#     request_type << 8
#     request marker
# ------------------------------------------------------------------

SHIZUKU_REQUEST_MARKER = 0x01


# ------------------------------------------------------------------
# Verified request types
# ------------------------------------------------------------------

SHIZUKU_REQUEST_PING = 0x08

SHIZUKU_REQUEST_LUA_MOSI = 0x1F


# ------------------------------------------------------------------
# Verified reply headers
# ------------------------------------------------------------------

SHIZUKU_PING_REPLY_HEADER = 0x80000009

SHIZUKU_LUA_MOSI_ACK_HEADER = 0x80000000


# ------------------------------------------------------------------
# Supported Fixed PDO command voltages
# ------------------------------------------------------------------

KT002_ALLOWED_FIXED_VOLTAGES = (
    5,
    9,
    12,
    15,
    20,
)


__all__ = [
    "KT002_USB_VID",
    "KT002_USB_PIDS",
    "KT002_USB_INTERFACE",
    "KT002_USB_EP_OUT",
    "KT002_USB_EP_IN",
    "KT002_USB_READ_SIZE",
    "SHIZUKU_FRAME_START",
    "SHIZUKU_FRAME_END",
    "SHIZUKU_MAX_PAYLOAD_SIZE",
    "SHIZUKU_REQUEST_MARKER",
    "SHIZUKU_REQUEST_PING",
    "SHIZUKU_REQUEST_LUA_MOSI",
    "SHIZUKU_PING_REPLY_HEADER",
    "SHIZUKU_LUA_MOSI_ACK_HEADER",
    "KT002_ALLOWED_FIXED_VOLTAGES",
]
