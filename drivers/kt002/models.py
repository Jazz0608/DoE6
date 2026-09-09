"""Data models for the POWER-Z KT002 direct-USB driver.

The models in this module contain decoded protocol and high-level command data.
They do not perform USB communication, Shizuku framing, Lua communication, or
USB-PD control.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class KT002Reply:
    """Decoded Shizuku protocol reply.

    Attributes:
        raw: Complete validated Shizuku frame.
        payload: Frame payload without the outer Shizuku framing bytes.
        header: Decoded 32-bit little-endian Shizuku message header.
        caller_id: Upper 16 bits of the decoded message header.
        message_type: Bits 8 through 15 of the decoded message header.
        low_byte: Lowest 8 bits of the decoded message header.
    """

    raw: bytes
    payload: bytes
    header: int
    caller_id: int
    message_type: int
    low_byte: int


@dataclass(frozen=True, slots=True)
class KT002CommandResult:
    """Structured result returned by a completed KT002 Lua command.

    Attributes:
        command: Normalized command sent to the KT002 Lua receiver.
        success: True when Lua reported successful command completion.
        raw_text: Original Lua MISO result line.
        message: Optional human-readable result or error message.
        data: Optional command-specific structured data.
    """

    command: str
    success: bool
    raw_text: str
    message: str | None = None
    data: Any | None = None


@dataclass(frozen=True, slots=True)
class KT002PDOResult:
    """Structured result of a successful Fixed PDO request.

    Example Lua MISO input:
        OK:PD_9V:8.926V:PDO=1

    Attributes:
        requested_voltage: Fixed PDO voltage requested by the caller, in volts.
        measured_voltage: Voltage measured by KT002 after the request, in volts.
        pdo_index: Source Capability index selected by the Lua controller.
        raw_text: Original Lua MISO result line.
        success: Always True for a successfully parsed OK result.
    """

    requested_voltage: int
    measured_voltage: float
    pdo_index: int
    raw_text: str
    success: bool = True

    @property
    def voltage_error(self) -> float:
        """Return measured voltage minus requested voltage, in volts."""

        return self.measured_voltage - self.requested_voltage

    @property
    def absolute_voltage_error(self) -> float:
        """Return the absolute voltage error, in volts."""

        return abs(self.voltage_error)


@dataclass(frozen=True, slots=True)
class KT002Capability:
    """One USB-PD Source Capability reported by KT002.

    This model is prepared for the later high-level CAPS API. Phase 3 does not
    assume that every field is available for every PDO type.
    """

    index: int
    pdo_type: str
    voltage: float | None = None
    maximum_voltage: float | None = None
    maximum_current: float | None = None
    maximum_power: float | None = None
    raw_text: str | None = None


@dataclass(frozen=True, slots=True)
class KT002MeterStatus:
    """High-level KT002 meter status returned by a future STATUS API.

    Optional fields allow the model to represent partial status reports without
    inventing values that were not supplied by the KT002 Lua controller.
    """

    voltage: float | None = None
    current: float | None = None
    power: float | None = None
    energy: float | None = None
    raw_text: str | None = None


__all__ = [
    "KT002Reply",
    "KT002CommandResult",
    "KT002PDOResult",
    "KT002Capability",
    "KT002MeterStatus",
]
