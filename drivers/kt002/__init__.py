"""Public interface for the modular POWER-Z KT002 driver.

Phase 3 exports the verified controller and transport APIs together with
structured result models, typed exceptions, and Lua MISO parsing helpers.
"""

from __future__ import annotations

from drivers.kt002.controller import KT002, KT002Controller
from drivers.kt002.exceptions import (
    KT002Error,
    KT002LuaError,
    KT002NotFoundError,
    KT002PDONotFoundError,
    KT002PDORequestError,
    KT002PDSourceError,
    KT002ProtocolError,
    KT002TimeoutError,
    KT002USBError,
    KT002VoltageVerificationError,
)
from drivers.kt002.models import (
    KT002Capability,
    KT002CommandResult,
    KT002MeterStatus,
    KT002PDOResult,
    KT002Reply,
)
from drivers.kt002.parser import (
    normalize_command,
    normalize_lua_line,
    parse_lua_result,
    parse_pdo_result,
    raise_for_lua_error,
)
from drivers.kt002.transport import KT002USBTransport


__all__ = [
    # Controller and transport
    "KT002",
    "KT002Controller",
    "KT002USBTransport",
    # Protocol and high-level result models
    "KT002Reply",
    "KT002CommandResult",
    "KT002PDOResult",
    "KT002Capability",
    "KT002MeterStatus",
    # Exception hierarchy
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
    # Lua MISO parser helpers
    "normalize_lua_line",
    "normalize_command",
    "parse_pdo_result",
    "raise_for_lua_error",
    "parse_lua_result",
]
