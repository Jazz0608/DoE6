"""
POWER-Z KT002 direct-USB driver package.

Public package interface for the modular KT002 driver.

Module structure:
    constants.py
        Verified USB and Shizuku protocol constants.

    exceptions.py
        KT002-specific exception hierarchy.

    models.py
        Decoded protocol data models.

    protocol.py
        Pure Shizuku frame encoding and decoding.

    transport.py
        PyUSB device discovery, interface management, and endpoint I/O.

    controller.py
        High-level KT002 control API used by DOE6.
"""

from __future__ import annotations

from drivers.kt002.controller import (
    KT002,
    KT002Controller,
)

from drivers.kt002.exceptions import (
    KT002Error,
    KT002NotFoundError,
    KT002ProtocolError,
    KT002TimeoutError,
    KT002USBError,
)

from drivers.kt002.models import (
    KT002Reply,
)

from drivers.kt002.transport import (
    KT002USBTransport,
)


__all__ = [
    "KT002",
    "KT002Controller",
    "KT002USBTransport",
    "KT002Reply",
    "KT002Error",
    "KT002NotFoundError",
    "KT002ProtocolError",
    "KT002TimeoutError",
    "KT002USBError",
]