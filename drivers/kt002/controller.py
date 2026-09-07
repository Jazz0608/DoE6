"""High-level controller for the POWER-Z KT002 direct-USB driver.

This module coordinates the dedicated constants, protocol, transport, model,
and exception modules. It provides the public KT002Controller API used by DOE6.
"""

from __future__ import annotations

import threading
import time

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
from drivers.kt002.exceptions import (
    KT002Error,
    KT002ProtocolError,
    KT002TimeoutError,
    KT002USBError,
)
from drivers.kt002.models import KT002Reply
from drivers.kt002.protocol import (
    extract_frames,
    pack_lua_mosi,
    pack_request,
)
from drivers.kt002.transport import KT002USBTransport


class KT002Controller:
    """Direct-USB controller for a POWER-Z KT002.

    The KT002 must run the verified onBoot.lua receiver before application
    commands such as ``PD_9V`` are sent.
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
        self._transport = (
            KT002USBTransport()
            if transport is None
            else transport
        )
        self._rx_buffer = bytearray()
        self._lock = threading.RLock()

        if auto_connect:
            self.connect()

    @property
    def connected(self) -> bool:
        """Return True when the KT002 USB interface is claimed."""
        return self._transport.connected

    @property
    def pid(self) -> int | None:
        """Return the connected KT002 PID, or None when disconnected."""
        return self._transport.pid

    @property
    def transport(self) -> KT002USBTransport:
        """Return the USB transport used by this controller."""
        return self._transport

    def _pack_request(
        self,
        request_type: int,
        arguments: bytes = b"",
    ) -> bytes:
        """Build a Shizuku request using the dedicated protocol module."""
        return pack_request(
            caller_id=self.caller_id,
            request_type=request_type,
            arguments=arguments,
        )

    def _pack_lua_mosi(self, content: bytes) -> bytes:
        """Build a Lua_MOSI request using the dedicated protocol module."""
        return pack_lua_mosi(
            content=content,
            caller_id=self.caller_id,
        )

    def connect(self) -> "KT002Controller":
        """Connect through the dedicated KT002 USB transport."""
        with self._lock:
            self._transport.connect()
            self._rx_buffer.clear()
            return self

    def close(self) -> None:
        """Release the KT002 USB transport and local receive state."""
        with self._lock:
            self._transport.close()
            self._rx_buffer.clear()

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
        """Decode complete frames using the dedicated protocol module."""
        return extract_frames(self._rx_buffer)

    def _write_and_wait_ack(
        self,
        packet: bytes,
        *,
        timeout: float | None = None,
    ) -> KT002Reply:
        self._require_connected()
        effective_timeout = self.timeout if timeout is None else float(timeout)

        if effective_timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        self._transport.write(packet)
        deadline = time.monotonic() + effective_timeout

        while time.monotonic() < deadline:
            remaining_ms = max(
                1,
                int((deadline - time.monotonic()) * 1000),
            )

            try:
                chunk = self._transport.read(
                    timeout_ms=min(250, remaining_ms),
                )
                self._rx_buffer.extend(chunk)
            except usb.core.USBTimeoutError:
                continue

            replies = self._extract_frames()
            if replies:
                return replies[0]

        raise KT002TimeoutError(
            "no valid KT002 acknowledgement before timeout"
        )

    def ping(self) -> KT002Reply:
        """Send the verified Shizuku protocol PING request."""
        with self._lock:
            self._drain_input()
            packet = self._pack_request(self.REQUEST_PING)
            reply = self._write_and_wait_ack(packet)

            if reply.header != self.PING_REPLY_HEADER:
                raise KT002ProtocolError(
                    "unexpected PING reply header "
                    f"0x{reply.header:08X}"
                )
            return reply

    def send_command(
        self,
        command: str,
        *,
        newline: bool = False,
    ) -> KT002Reply:
        """Send one command to the running onBoot.lua via Lua_MOSI."""
        if not isinstance(command, str):
            raise TypeError("command must be a string")

        normalized = command.strip()
        if not normalized:
            raise ValueError("command must not be empty")

        content = (
            normalized + ("\n" if newline else "")
        ).encode("utf-8")

        with self._lock:
            self._drain_input()
            packet = self._pack_lua_mosi(content)
            reply = self._write_and_wait_ack(packet)

            if reply.header != self.LUA_MOSI_ACK_HEADER:
                raise KT002ProtocolError(
                    "unexpected Lua_MOSI ACK header "
                    f"0x{reply.header:08X}"
                )
            return reply

    def lua_ping(self) -> KT002Reply:
        """Ask onBoot.lua to process PING."""
        return self.send_command("PING")

    def initialize_pd(self) -> KT002Reply:
        """Ask onBoot.lua to initialize PD, if supported."""
        return self.send_command("INIT")

    def request_capabilities(self) -> KT002Reply:
        """Ask onBoot.lua to report source capabilities, if supported."""
        return self.send_command("CAPS")

    def request_status(self) -> KT002Reply:
        """Ask onBoot.lua to report meter status, if supported."""
        return self.send_command("STATUS")

    def set_voltage(self, voltage: int) -> KT002Reply:
        """Request a supported fixed PDO through onBoot.lua.

        The returned reply confirms the Lua_MOSI protocol acknowledgement.
        DOE6 must verify actual VBUS before enabling the electronic load.
        """
        if voltage not in self.ALLOWED_VOLTAGES:
            allowed = ", ".join(
                str(value) for value in self.ALLOWED_VOLTAGES
            )
            raise ValueError(
                f"unsupported voltage {voltage}; allowed: {allowed}"
            )

        return self.send_command(f"PD_{voltage}V")

    def release(self) -> KT002Reply:
        """Ask onBoot.lua to execute its RELEASE command."""
        return self.send_command("RELEASE")

    def clear_display(self) -> KT002Reply:
        """Ask onBoot.lua to clear its display, if supported."""
        return self.send_command("CLEAR")


KT002 = KT002Controller


__all__ = [
    "KT002",
    "KT002Controller",
]
