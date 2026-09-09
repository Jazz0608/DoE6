"""Exception hierarchy for the POWER-Z KT002 direct-USB driver.

All KT002-specific exceptions inherit from KT002Error. Callers may catch a
specific failure type or catch KT002Error as the common driver-level base.
"""

from __future__ import annotations


class KT002Error(RuntimeError):
    """Base exception for all KT002 driver errors."""


class KT002NotFoundError(KT002Error):
    """Raised when no supported KT002 USB device is found."""


class KT002USBError(KT002Error):
    """Raised when a KT002 USB transport operation fails."""


class KT002TimeoutError(KT002Error):
    """Raised when an expected KT002 reply is not received before timeout."""


class KT002ProtocolError(KT002Error):
    """Raised when a malformed or unexpected Shizuku frame is received."""


class KT002LuaError(KT002Error):
    """Base exception for errors reported by the KT002 Lua controller.

    Attributes:
        raw_text: Original Lua MISO error line, when available.
        command: Command associated with the error, when available.
    """

    def __init__(
        self,
        message: str,
        *,
        raw_text: str | None = None,
        command: str | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.command = command


class KT002PDSourceError(KT002LuaError):
    """Raised when no valid USB-PD source or Source Capability is available."""


class KT002PDONotFoundError(KT002LuaError):
    """Raised when the requested Fixed PDO is not advertised by the source.

    Attributes:
        requested_voltage: Requested Fixed PDO voltage in volts, if known.
    """

    def __init__(
        self,
        message: str,
        *,
        requested_voltage: int | None = None,
        raw_text: str | None = None,
        command: str | None = None,
    ) -> None:
        super().__init__(message, raw_text=raw_text, command=command)
        self.requested_voltage = requested_voltage


class KT002PDORequestError(KT002LuaError):
    """Raised when KT002 cannot complete a requested PDO transition.

    Attributes:
        requested_voltage: Requested Fixed PDO voltage in volts, if known.
        pdo_index: PDO index associated with the failed request, if known.
    """

    def __init__(
        self,
        message: str,
        *,
        requested_voltage: int | None = None,
        pdo_index: int | None = None,
        raw_text: str | None = None,
        command: str | None = None,
    ) -> None:
        super().__init__(message, raw_text=raw_text, command=command)
        self.requested_voltage = requested_voltage
        self.pdo_index = pdo_index


class KT002VoltageVerificationError(KT002Error):
    """Raised when measured VBUS is outside the permitted voltage tolerance.

    Attributes:
        requested_voltage: Requested voltage in volts.
        measured_voltage: Measured voltage in volts.
        tolerance: Permitted absolute deviation in volts.
    """

    def __init__(
        self,
        message: str,
        *,
        requested_voltage: float,
        measured_voltage: float,
        tolerance: float,
    ) -> None:
        super().__init__(message)
        self.requested_voltage = requested_voltage
        self.measured_voltage = measured_voltage
        self.tolerance = tolerance

    @property
    def voltage_error(self) -> float:
        """Return measured voltage minus requested voltage, in volts."""

        return self.measured_voltage - self.requested_voltage

    @property
    def absolute_voltage_error(self) -> float:
        """Return the absolute voltage error, in volts."""

        return abs(self.voltage_error)


__all__ = [
    "KT002Error",
    "KT002NotFoundError",
    "KT002USBError",
    "KT002TimeoutError",
    "KT002ProtocolError",
    "KT002LuaError",
    "KT002PDSourceError",
    "KT002PDONotFoundError",
    "KT002PDORequestError",
    "KT002VoltageVerificationError",
]
