"""
Exception hierarchy for the POWER-Z KT002 direct-USB driver.

All KT002-specific exceptions inherit from KT002Error so callers can
either handle individual failure types or catch KT002Error as the
common base exception.
"""


class KT002Error(RuntimeError):
    """Base exception for all KT002 driver errors."""


class KT002NotFoundError(KT002Error):
    """Raised when no supported KT002 USB device is found."""


class KT002USBError(KT002Error):
    """Raised when a KT002 USB transport operation fails."""


class KT002TimeoutError(KT002Error):
    """Raised when KT002 does not reply before the timeout expires."""


class KT002ProtocolError(KT002Error):
    """Raised when a malformed or unexpected protocol frame is received."""


__all__ = [
    "KT002Error",
    "KT002NotFoundError",
    "KT002USBError",
    "KT002TimeoutError",
    "KT002ProtocolError",
]
