"""High-level controller for the POWER-Z KT002 direct-USB driver.

Phase 2 adds verified Lua MISO text reception while preserving the Phase 1
Protocol PING, Lua_MOSI ACK, USB transport, and Fixed PDO command behavior.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import usb.core

from drivers.kt002.constants import (
    KT002_ALLOWED_FIXED_VOLTAGES,
    KT002_USB_EP_IN,
    KT002_USB_EP_OUT,
    KT002_USB_INTERFACE,
    KT002_USB_PIDS,
    KT002_USB_READ_SIZE,
    KT002_USB_VID,
    SHIZUKU_FRAME_END,
    SHIZUKU_FRAME_START,
    SHIZUKU_LUA_MOSI_ACK_HEADER,
    SHIZUKU_MAX_PAYLOAD_SIZE,
    SHIZUKU_PING_REPLY_HEADER,
    SHIZUKU_REQUEST_LUA_MOSI,
    SHIZUKU_REQUEST_MARKER,
    SHIZUKU_REQUEST_PING,
)
from drivers.kt002.exceptions import KT002TimeoutError, KT002USBError
from drivers.kt002.models import KT002Reply
from drivers.kt002.protocol import extract_frames, pack_lua_mosi, pack_request
from drivers.kt002.transport import KT002USBTransport


class KT002Controller:
    """Direct-USB controller for a POWER-Z KT002.

    Phase 1 methods continue to return protocol acknowledgements. Phase 2
    methods ending in ``_wait_result`` additionally wait for Lua MISO text.
    """

    VID = KT002_USB_VID
    VALID_PIDS = KT002_USB_PIDS
    INTERFACE = KT002_USB_INTERFACE
    EP_OUT = KT002_USB_EP_OUT
    EP_IN = KT002_USB_EP_IN
    READ_SIZE = KT002_USB_READ_SIZE

    FRAME_START = SHIZUKU_FRAME_START
    FRAME_END = SHIZUKU_FRAME_END
    MAX_PAYLOAD = SHIZUKU_MAX_PAYLOAD_SIZE

    REQUEST_MARKER = SHIZUKU_REQUEST_MARKER
    REQUEST_PING = SHIZUKU_REQUEST_PING
    REQUEST_LUA_MOSI = SHIZUKU_REQUEST_LUA_MOSI
    PING_REPLY_HEADER = SHIZUKU_PING_REPLY_HEADER
    LUA_MOSI_ACK_HEADER = SHIZUKU_LUA_MOSI_ACK_HEADER
    ALLOWED_VOLTAGES = KT002_ALLOWED_FIXED_VOLTAGES

    LUA_PUTCHAR_SETUP_REQUEST = 0x10
    LUA_PUTCHAR_CALLER_ID = 1
    LUA_PUTCHAR_SETUP_ACK = 0x80010003
    LUA_TEXT_REPORT_TYPE = 0x10

    def __init__(
        self,
        *,
        timeout: float = 3.0,
        caller_id: int = 0,
        auto_connect: bool = False,
        transport: KT002USBTransport | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if not 0 <= caller_id <= 0xFFFF:
            raise ValueError("caller_id must be within 0..65535")

        self.timeout = float(timeout)
        self.caller_id = caller_id
        self._transport = KT002USBTransport() if transport is None else transport
        self._rx_buffer = bytearray()
        self._lock = threading.RLock()
        self._lua_miso_registered = False

        if auto_connect:
            self.connect()

    @property
    def connected(self) -> bool:
        return self._transport.connected

    @property
    def pid(self) -> int | None:
        return self._transport.pid

    @property
    def transport(self) -> KT002USBTransport:
        return self._transport

    @property
    def lua_miso_registered(self) -> bool:
        return self._lua_miso_registered

    def _pack_request(self, request_type: int, arguments: bytes = b"") -> bytes:
        return pack_request(
            caller_id=self.caller_id,
            request_type=request_type,
            arguments=arguments,
        )

    def _pack_lua_mosi(self, content: bytes) -> bytes:
        return pack_lua_mosi(content=content, caller_id=self.caller_id)

    def connect(self) -> "KT002Controller":
        with self._lock:
            self._transport.connect()
            self._rx_buffer.clear()
            self._lua_miso_registered = False
            return self

    def close(self) -> None:
        with self._lock:
            self._transport.close()
            self._rx_buffer.clear()
            self._lua_miso_registered = False

    def __enter__(self) -> "KT002Controller":
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _require_connected(self) -> None:
        if not self.connected:
            raise KT002USBError("KT002 is not connected")

    def _drain_input(self) -> None:
        self._require_connected()
        self._rx_buffer.clear()
        self._transport.drain_input()

    def _extract_frames(self) -> list[KT002Reply]:
        return extract_frames(self._rx_buffer)

    def _read_frames_until(self, deadline: float) -> Iterator[KT002Reply]:
        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            try:
                chunk = self._transport.read(
                    timeout_ms=min(250, remaining_ms),
                )
                self._rx_buffer.extend(chunk)
            except usb.core.USBTimeoutError:
                continue

            yield from self._extract_frames()

    def _write_and_wait_ack(
        self,
        packet: bytes,
        *,
        expected_header: int,
        timeout: float | None = None,
    ) -> KT002Reply:
        """Write a request and wait for the exact expected ACK Header.

        Periodic Reports and Lua MISO text Reports are ignored here. This keeps
        Phase 1 ping() and send_command() compatible after MISO registration.
        """
        self._require_connected()
        effective_timeout = self.timeout if timeout is None else float(timeout)
        if effective_timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if not isinstance(expected_header, int):
            raise TypeError("expected_header must be an integer")
        if not 0 <= expected_header <= 0xFFFFFFFF:
            raise ValueError("expected_header must be within 0..0xFFFFFFFF")

        self._transport.write(packet)
        deadline = time.monotonic() + effective_timeout

        for reply in self._read_frames_until(deadline):
            if reply.header == expected_header:
                return reply

        raise KT002TimeoutError(
            "expected KT002 acknowledgement "
            f"0x{expected_header:08X} was not received before timeout"
        )

    @classmethod
    def decode_lua_miso_text(cls, reply: KT002Reply) -> str | None:
        """Decode one verified Type 0x10 Lua text Report."""
        if reply.message_type != cls.LUA_TEXT_REPORT_TYPE:
            return None
        if len(reply.payload) < 4:
            return None
        return reply.payload[4:].decode("utf-8", errors="replace")

    def register_lua_miso(self, *, timeout: float = 2.0) -> KT002Reply:
        """Register Lua putchar Reports and return ACK 0x80010003."""
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        with self._lock:
            self._require_connected()
            self._drain_input()
            packet = pack_request(
                caller_id=self.LUA_PUTCHAR_CALLER_ID,
                request_type=self.LUA_PUTCHAR_SETUP_REQUEST,
            )
            self._transport.write(packet)
            deadline = time.monotonic() + timeout

            for reply in self._read_frames_until(deadline):
                if reply.header == self.LUA_PUTCHAR_SETUP_ACK:
                    self._lua_miso_registered = True
                    return reply

            raise KT002TimeoutError(
                "Lua putchar setup ACK 0x80010003 was not received"
            )

    def send_command_wait_result(
        self,
        command: str,
        *,
        expected: str,
        timeout: float = 5.0,
    ) -> str:
        """Send Lua_MOSI and wait for both ACK and expected Lua MISO text."""
        if not isinstance(command, str):
            raise TypeError("command must be a string")
        if not isinstance(expected, str):
            raise TypeError("expected must be a string")

        normalized = command.strip()
        if not normalized:
            raise ValueError("command must not be empty")
        if not expected:
            raise ValueError("expected must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        with self._lock:
            self._require_connected()
            if not self._lua_miso_registered:
                self.register_lua_miso()

            self._drain_input()
            self._transport.write(
                self._pack_lua_mosi(normalized.encode("utf-8"))
            )

            ack_received = False
            text_buffer = ""
            matched_line: str | None = None
            deadline = time.monotonic() + timeout

            for reply in self._read_frames_until(deadline):
                if reply.header == self.LUA_MOSI_ACK_HEADER:
                    ack_received = True
                    if matched_line is not None:
                        return matched_line
                    continue

                text = self.decode_lua_miso_text(reply)
                if text is None:
                    continue

                text_buffer += text
                if expected in text_buffer:
                    matched_line = expected
                    for line in text_buffer.splitlines():
                        if expected in line:
                            matched_line = line
                            break
                    if ack_received:
                        return matched_line

            if not ack_received:
                raise KT002TimeoutError(
                    "Lua_MOSI ACK 0x80000000 was not received"
                )
            raise KT002TimeoutError(
                f"Lua MISO text {expected!r} was not received before timeout"
            )

    def ping(self) -> KT002Reply:
        with self._lock:
            self._drain_input()
            return self._write_and_wait_ack(
                self._pack_request(self.REQUEST_PING),
                expected_header=self.PING_REPLY_HEADER,
            )

    def send_command(
        self,
        command: str,
        *,
        newline: bool = False,
    ) -> KT002Reply:
        """Send Lua_MOSI and return its exact protocol ACK."""
        if not isinstance(command, str):
            raise TypeError("command must be a string")

        normalized = command.strip()
        if not normalized:
            raise ValueError("command must not be empty")

        content = (normalized + ("\n" if newline else "")).encode("utf-8")
        with self._lock:
            self._drain_input()
            return self._write_and_wait_ack(
                self._pack_lua_mosi(content),
                expected_header=self.LUA_MOSI_ACK_HEADER,
            )

    def lua_ping(self) -> KT002Reply:
        return self.send_command("PING")

    def lua_ping_wait_result(self, *, timeout: float = 5.0) -> str:
        return self.send_command_wait_result(
            "PING",
            expected="PONG:KT002",
            timeout=timeout,
        )

    def initialize_pd(self) -> KT002Reply:
        return self.send_command("INIT")

    def request_capabilities(self) -> KT002Reply:
        return self.send_command("CAPS")

    def request_status(self) -> KT002Reply:
        return self.send_command("STATUS")

    def set_voltage(self, voltage: int) -> KT002Reply:
        if voltage not in self.ALLOWED_VOLTAGES:
            allowed = ", ".join(str(value) for value in self.ALLOWED_VOLTAGES)
            raise ValueError(
                f"unsupported voltage {voltage}; allowed: {allowed}"
            )
        return self.send_command(f"PD_{voltage}V")

    def set_voltage_wait_result(
        self,
        voltage: int,
        *,
        timeout: float = 8.0,
    ) -> str:
        """Request a Fixed PDO and wait for its Lua OK result line."""
        if voltage not in self.ALLOWED_VOLTAGES:
            allowed = ", ".join(str(value) for value in self.ALLOWED_VOLTAGES)
            raise ValueError(
                f"unsupported voltage {voltage}; allowed: {allowed}"
            )
        return self.send_command_wait_result(
            f"PD_{voltage}V",
            expected=f"OK:PD_{voltage}V:",
            timeout=timeout,
        )

    def release(self) -> KT002Reply:
        return self.send_command("RELEASE")

    def clear_display(self) -> KT002Reply:
        return self.send_command("CLEAR")


KT002 = KT002Controller


__all__ = [
    "KT002",
    "KT002Controller",
]
