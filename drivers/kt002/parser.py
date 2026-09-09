"""Lua MISO response parser for the POWER-Z KT002 driver.

This module converts verified KT002 Lua text lines into Phase 3 structured
results or typed exceptions. It performs no USB I/O, Shizuku framing, callback
registration, PDO switching, or voltage measurement.
"""

from __future__ import annotations

import re

from drivers.kt002.exceptions import (
    KT002LuaError,
    KT002PDONotFoundError,
    KT002PDORequestError,
    KT002PDSourceError,
)
from drivers.kt002.models import KT002CommandResult, KT002PDOResult


_PDO_OK_PATTERN = re.compile(
    r"^OK:PD_(?P<voltage>5|9|12|15|20)V:"
    r"(?P<measured>[0-9]+(?:\.[0-9]+)?)V:"
    r"PDO=(?P<pdo_index>[0-9]+)$"
)

_PDO_NOT_FOUND_PATTERN = re.compile(
    r"^ERROR:PDO_(?P<voltage>[0-9]+)V_NOT_FOUND$"
)

_PDO_REQUEST_FAILED_PATTERN = re.compile(
    r"^ERROR:REQUEST_FAILED:PD_(?P<voltage>[0-9]+)V:"
    r"PDO=(?P<pdo_index>[0-9]+)$"
)

_PD_INITIALIZED_PATTERN = re.compile(
    r"^OK:PD_INITIALIZED:(?P<count>[0-9]+)$"
)


_PD_SOURCE_ERRORS = {
    "ERROR:NO_PD_SOURCE": "No USB-PD source is attached",
    "ERROR:SOURCE_CAP_TIMEOUT": "Timed out waiting for Source Capabilities",
    "ERROR:NO_SOURCE_CAPABILITY": "No USB-PD Source Capability is available",
    "ERROR:FASTCHG_OPEN_FAILED": "Unable to open the KT002 fast-charge interface",
}


def normalize_lua_line(text: str) -> str:
    """Return one normalized Lua MISO response line.

    Leading and trailing whitespace, CR, and LF are removed. Embedded content
    is preserved. An empty result is rejected because it cannot represent a
    completed KT002 command.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    normalized = text.strip()
    if not normalized:
        raise ValueError("Lua MISO response must not be empty")

    return normalized


def normalize_command(command: str | None) -> str | None:
    """Normalize an optional command for result and exception metadata."""

    if command is None:
        return None
    if not isinstance(command, str):
        raise TypeError("command must be a string or None")

    normalized = command.strip().upper()
    if not normalized:
        raise ValueError("command must not be empty")

    return normalized


def parse_pdo_result(text: str) -> KT002PDOResult:
    """Parse a successful Fixed PDO Lua MISO result.

    Accepted format:
        OK:PD_9V:8.926V:PDO=1

    Raises:
        KT002LuaError: If the line is not a valid successful PDO result.
    """

    raw_text = normalize_lua_line(text)
    match = _PDO_OK_PATTERN.fullmatch(raw_text)

    if match is None:
        raise KT002LuaError(
            "Invalid KT002 PDO result format",
            raw_text=raw_text,
        )

    return KT002PDOResult(
        requested_voltage=int(match.group("voltage")),
        measured_voltage=float(match.group("measured")),
        pdo_index=int(match.group("pdo_index")),
        raw_text=raw_text,
    )


def raise_for_lua_error(
    text: str,
    *,
    command: str | None = None,
) -> None:
    """Raise the typed Phase 3 exception represented by a Lua error line.

    The function returns normally only when ``text`` is not an ERROR line.
    """

    raw_text = normalize_lua_line(text)
    normalized_command = normalize_command(command)

    if not raw_text.startswith("ERROR:"):
        return

    match = _PDO_NOT_FOUND_PATTERN.fullmatch(raw_text)
    if match is not None:
        voltage = int(match.group("voltage"))
        raise KT002PDONotFoundError(
            f"{voltage}V Fixed PDO is not available",
            requested_voltage=voltage,
            raw_text=raw_text,
            command=normalized_command,
        )

    match = _PDO_REQUEST_FAILED_PATTERN.fullmatch(raw_text)
    if match is not None:
        voltage = int(match.group("voltage"))
        pdo_index = int(match.group("pdo_index"))
        raise KT002PDORequestError(
            f"KT002 failed to request {voltage}V using PDO {pdo_index}",
            requested_voltage=voltage,
            pdo_index=pdo_index,
            raw_text=raw_text,
            command=normalized_command,
        )

    source_message = _PD_SOURCE_ERRORS.get(raw_text)
    if source_message is not None:
        raise KT002PDSourceError(
            source_message,
            raw_text=raw_text,
            command=normalized_command,
        )

    if raw_text.startswith("ERROR:LUA:"):
        detail = raw_text.removeprefix("ERROR:LUA:").strip()
        raise KT002LuaError(
            detail or "KT002 Lua runtime error",
            raw_text=raw_text,
            command=normalized_command,
        )

    if raw_text.startswith("ERROR:UNKNOWN_COMMAND:"):
        unknown = raw_text.removeprefix("ERROR:UNKNOWN_COMMAND:").strip()
        raise KT002LuaError(
            f"KT002 Lua controller rejected unknown command {unknown!r}",
            raw_text=raw_text,
            command=normalized_command,
        )

    raise KT002LuaError(
        f"KT002 Lua controller reported an error: {raw_text}",
        raw_text=raw_text,
        command=normalized_command,
    )


def parse_lua_result(
    text: str,
    *,
    command: str | None = None,
) -> KT002CommandResult | KT002PDOResult:
    """Parse one completed KT002 Lua MISO response line.

    Successful PDO lines become ``KT002PDOResult``. Other known successful
    lines become ``KT002CommandResult``. ERROR lines raise typed exceptions.
    """

    raw_text = normalize_lua_line(text)
    normalized_command = normalize_command(command)

    raise_for_lua_error(raw_text, command=normalized_command)

    if _PDO_OK_PATTERN.fullmatch(raw_text) is not None:
        result = parse_pdo_result(raw_text)

        if normalized_command is not None:
            expected_command = f"PD_{result.requested_voltage}V"
            if normalized_command != expected_command:
                raise KT002LuaError(
                    "Lua PDO result does not match the requested command",
                    raw_text=raw_text,
                    command=normalized_command,
                )

        return result

    if raw_text == "PONG:KT002":
        return KT002CommandResult(
            command=normalized_command or "PING",
            success=True,
            raw_text=raw_text,
            message="KT002 Lua controller is online",
        )

    if raw_text.startswith("READY:KT002_"):
        return KT002CommandResult(
            command=normalized_command or "STARTUP",
            success=True,
            raw_text=raw_text,
            message="KT002 Lua controller is ready",
        )

    match = _PD_INITIALIZED_PATTERN.fullmatch(raw_text)
    if match is not None:
        capability_count = int(match.group("count"))
        return KT002CommandResult(
            command=normalized_command or "INIT",
            success=True,
            raw_text=raw_text,
            message="USB-PD initialization completed",
            data={"source_capability_count": capability_count},
        )

    if raw_text.startswith("OK:"):
        return KT002CommandResult(
            command=normalized_command or "UNKNOWN",
            success=True,
            raw_text=raw_text,
            message=raw_text.removeprefix("OK:"),
        )

    raise KT002LuaError(
        "Unrecognized KT002 Lua MISO result",
        raw_text=raw_text,
        command=normalized_command,
    )


__all__ = [
    "normalize_lua_line",
    "normalize_command",
    "parse_pdo_result",
    "raise_for_lua_error",
    "parse_lua_result",
]
