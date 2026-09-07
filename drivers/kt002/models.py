"""
Data models for the POWER-Z KT002 direct-USB driver.

These models contain decoded protocol data only. They do not perform USB
communication, frame encoding, PDO control, or hardware operations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KT002Reply:
    """
    Decoded Shizuku protocol reply.

    Attributes:
        raw:
            Complete validated Shizuku frame, including the 0xA5 start byte,
            payload length, payload, XOR byte, and 0x5A end byte.

        payload:
            Frame payload without the outer Shizuku framing bytes.

        header:
            Decoded 32-bit little-endian Shizuku message header.

        caller_id:
            Upper 16 bits of the decoded message header.

        message_type:
            Bits 8 through 15 of the decoded message header.

        low_byte:
            Lowest 8 bits of the decoded message header.
    """

    raw: bytes
    payload: bytes
    header: int
    caller_id: int
    message_type: int
    low_byte: int


__all__ = [
    "KT002Reply",
]
