"""POWER-Z KT002 direct-USB driver for Raspberry Pi.

This driver communicates directly with the KT002 Shizuku protocol. It does not
require Windows or KT Toolbox. It is designed to work with the verified
``onBoot.lua`` command receiver running on the KT002.

Verified transport:
    VID             0x0483
    PID             0xFFFF, 0xFFFE, or 0x374B
    USB interface   0
    Bulk OUT        0x01
    Bulk IN         0x81

Verified frame format:
    A5 + uint32_le(payload_length) + payload + xor(payload) + 5A

Verified requests used here:
    0x08  Protocol PING
    0x1F  Lua_MOSI

The Lua_MOSI acknowledgement proves the command was accepted by the KT002
firmware. Application-level success is verified by the onBoot.lua display and,
for DOE operation, by the downstream electronic-load voltage measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
import threading
import time
from typing import Iterable

import usb.core
import usb.util


class KT002Error(RuntimeError):
    """Base exception for KT002 driver errors."""


class KT002NotFoundError(KT002Error):
    """Raised when no supported KT002 USB device is found."""


class KT002USBError(KT002Error):
    """Raised for USB transport failures."""


class KT002TimeoutError(KT002Error):
    """Raised when the KT002 does not return a valid protocol frame in time."""


class KT002ProtocolError(KT002Error):
    """Raised when a malformed or unexpected protocol frame is received."""


@dataclass(frozen=True)
class KT002Reply:
    """Decoded Shizuku protocol reply."""

    raw: bytes
    payload: bytes
    header: int
    caller_id: int
    message_type: int
    low_byte: int


class KT002Controller:
    """Direct-USB controller for a POWER-Z KT002.

    Use as a context manager where possible::

        with KT002Controller() as kt002:
            kt002.ping()
            kt002.set_voltage(9)

    The KT002 must be running the verified onBoot.lua command receiver before
    application commands such as ``PD_9V`` are sent.
    """

    VID = 0x0483
    VALID_PIDS = (0xFFFF, 0xFFFE, 0x374B)

    INTERFACE = 0
    EP_OUT = 0x01
    EP_IN = 0x81
    READ_SIZE = 4096

    FRAME_START = 0xA5
    FRAME_END = 0x5A
    MAX_PAYLOAD = 4096

    REQUEST_MARKER = 0x01
    REQUEST_PING = 0x08
    REQUEST_LUA_MOSI = 0x1F

    ALLOWED_VOLTAGES = (5, 9, 12, 15, 20)

    def __init__(
        self,
        *,
        timeout: float = 3.0,
        caller_id: int = 0,
        auto_connect: bool = False,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if not 0 <= caller_id <= 0xFFFF:
            raise ValueError("caller_id must be within 0..65535")

        self.timeout = float(timeout)
        self.caller_id = caller_id
        self._device = None
        self._pid: int | None = None
        self._claimed = False
        self._detached_kernel_driver = False
        self._rx_buffer = bytearray()
        self._lock = threading.RLock()

        if auto_connect:
            self.connect()

    @property
    def connected(self) -> bool:
        return self._device is not None and self._claimed

    @property
    def pid(self) -> int | None:
        return self._pid

    @staticmethod
    def _xor8(data: bytes) -> int:
        value = 0
        for byte in data:
            value ^= byte
        return value

    @classmethod
    def _pack_frame(cls, payload: bytes) -> bytes:
        if len(payload) > cls.MAX_PAYLOAD:
            raise ValueError(f"payload exceeds {cls.MAX_PAYLOAD} bytes")
        return (
            bytes((cls.FRAME_START,))
            + struct.pack("<I", len(payload))
            + payload
            + bytes((cls._xor8(payload), cls.FRAME_END))
        )

    def _pack_request(
        self,
        request_type: int,
        arguments: bytes = b"",
    ) -> bytes:
        header = (
            (self.caller_id << 16)
            | ((request_type & 0xFF) << 8)
            | self.REQUEST_MARKER
        )
        return self._pack_frame(struct.pack("<I", header) + arguments)

    def _pack_lua_mosi(self, content: bytes) -> bytes:
        if not content:
            raise ValueError("Lua_MOSI content must not be empty")
        if len(content) > 0xFFFF:
            raise ValueError("Lua_MOSI content exceeds 65535 bytes")

        # Exact argument layout recovered from ShizukuProtocol.dll.
        uint32_count = ((len(content) + 3) // 4) + 4
        arguments = bytearray(uint32_count * 4)
        struct.pack_into("<I", arguments, 0, len(content) << 16)
        arguments[4:4 + len(content)] = content
        return self._pack_request(self.REQUEST_LUA_MOSI, bytes(arguments))

    def _find_device(self):
        for pid in self.VALID_PIDS:
            device = usb.core.find(idVendor=self.VID, idProduct=pid)
            if device is not None:
                return device, pid
        return None, None

    def connect(self) -> "KT002Controller":
        """Find, open, and claim the KT002 direct-USB interface."""
        with self._lock:
            if self.connected:
                return self

            device, pid = self._find_device()
            if device is None:
                raise KT002NotFoundError(
                    "KT002 not found. Expected VID 0483 and PID FFFF/FFFE/374B."
                )

            self._device = device
            self._pid = pid

            try:
                try:
                    if device.is_kernel_driver_active(self.INTERFACE):
                        device.detach_kernel_driver(self.INTERFACE)
                        self._detached_kernel_driver = True
                except (NotImplementedError, usb.core.USBError):
                    pass

                # Do not call set_configuration(). KT002 is a composite USB
                # device and changing configuration can produce Resource busy.
                usb.util.claim_interface(device, self.INTERFACE)
                self._claimed = True

                for endpoint in (self.EP_OUT, self.EP_IN):
                    try:
                        device.clear_halt(endpoint)
                    except usb.core.USBError:
                        pass

                self._drain_input()
                return self

            except usb.core.USBError as exc:
                self.close()
                raise KT002USBError(f"Unable to claim KT002 interface 0: {exc}") from exc

    def close(self) -> None:
        """Release USB resources and restore the Linux kernel driver."""
        with self._lock:
            device = self._device
            if device is None:
                return

            if self._claimed:
                try:
                    usb.util.release_interface(device, self.INTERFACE)
                except usb.core.USBError:
                    pass

            usb.util.dispose_resources(device)

            if self._detached_kernel_driver:
                try:
                    device.attach_kernel_driver(self.INTERFACE)
                except (NotImplementedError, usb.core.USBError):
                    pass

            self._device = None
            self._pid = None
            self._claimed = False
            self._detached_kernel_driver = False
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
        while True:
            try:
                self._device.read(self.EP_IN, self.READ_SIZE, timeout=50)
            except usb.core.USBTimeoutError:
                return
            except usb.core.USBError as exc:
                raise KT002USBError(f"Unable to drain KT002 input: {exc}") from exc

    def _extract_frames(self) -> list[KT002Reply]:
        replies: list[KT002Reply] = []

        while True:
            try:
                start = self._rx_buffer.index(self.FRAME_START)
            except ValueError:
                self._rx_buffer.clear()
                break

            if start:
                del self._rx_buffer[:start]

            if len(self._rx_buffer) < 7:
                break

            payload_length = struct.unpack_from("<I", self._rx_buffer, 1)[0]
            if payload_length > self.MAX_PAYLOAD:
                del self._rx_buffer[0]
                continue

            frame_length = payload_length + 7
            if len(self._rx_buffer) < frame_length:
                break

            raw = bytes(self._rx_buffer[:frame_length])
            del self._rx_buffer[:frame_length]
            payload = raw[5:5 + payload_length]

            if raw[-1] != self.FRAME_END:
                raise KT002ProtocolError("invalid KT002 frame terminator")
            if raw[-2] != self._xor8(payload):
                raise KT002ProtocolError("invalid KT002 frame XOR")
            if len(payload) < 4:
                raise KT002ProtocolError("KT002 reply payload is shorter than 4 bytes")

            header = struct.unpack_from("<I", payload, 0)[0]
            replies.append(
                KT002Reply(
                    raw=raw,
                    payload=payload,
                    header=header,
                    caller_id=(header >> 16) & 0xFFFF,
                    message_type=(header >> 8) & 0xFF,
                    low_byte=header & 0xFF,
                )
            )

        return replies

    def _write_and_wait_ack(
        self,
        packet: bytes,
        *,
        timeout: float | None = None,
    ) -> KT002Reply:
        self._require_connected()
        effective_timeout = self.timeout if timeout is None else float(timeout)

        try:
            written = self._device.write(self.EP_OUT, packet, timeout=2000)
        except usb.core.USBError as exc:
            raise KT002USBError(f"KT002 USB write failed: {exc}") from exc

        if written != len(packet):
            raise KT002USBError(
                f"short KT002 USB write: {written} of {len(packet)} bytes"
            )

        deadline = time.monotonic() + effective_timeout

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            try:
                chunk = bytes(
                    self._device.read(
                        self.EP_IN,
                        self.READ_SIZE,
                        timeout=min(250, remaining_ms),
                    )
                )
                self._rx_buffer.extend(chunk)
            except usb.core.USBTimeoutError:
                continue
            except usb.core.USBError as exc:
                raise KT002USBError(f"KT002 USB read failed: {exc}") from exc

            replies = self._extract_frames()
            if replies:
                return replies[0]

        raise KT002TimeoutError("no valid KT002 acknowledgement before timeout")

    def ping(self) -> KT002Reply:
        """Send the verified Shizuku protocol PING request."""
        with self._lock:
            self._drain_input()
            packet = self._pack_request(self.REQUEST_PING)
            reply = self._write_and_wait_ack(packet)

            # Verified KT002 PING reply header is 0x80000009.
            if reply.header != 0x80000009:
                raise KT002ProtocolError(
                    f"unexpected PING reply header 0x{reply.header:08X}"
                )
            return reply

    def send_command(
        self,
        command: str,
        *,
        newline: bool = False,
    ) -> KT002Reply:
        """Send one command to the running onBoot.lua via Lua_MOSI.

        The verified onBoot.lua uses ``tcp.readAll()`` and does not require a
        newline. Set ``newline=True`` only for a Lua receiver that expects one.
        """
        if not isinstance(command, str):
            raise TypeError("command must be a string")

        normalized = command.strip()
        if not normalized:
            raise ValueError("command must not be empty")

        content = (normalized + ("\n" if newline else "")).encode("utf-8")

        with self._lock:
            self._drain_input()
            packet = self._pack_lua_mosi(content)
            reply = self._write_and_wait_ack(packet)

            # Verified successful Lua_MOSI acknowledgement.
            if reply.header != 0x80000000:
                raise KT002ProtocolError(
                    f"unexpected Lua_MOSI ACK header 0x{reply.header:08X}"
                )
            return reply

    def lua_ping(self) -> KT002Reply:
        """Ask onBoot.lua to process PING and show Raspberry Pi connected."""
        return self.send_command("PING")

    def initialize_pd(self) -> KT002Reply:
        """Ask onBoot.lua to initialize PD and cache source capabilities."""
        return self.send_command("INIT")

    def request_capabilities(self) -> KT002Reply:
        """Ask onBoot.lua to enumerate source capabilities."""
        return self.send_command("CAPS")

    def request_status(self) -> KT002Reply:
        """Ask onBoot.lua to report its current meter status."""
        return self.send_command("STATUS")

    def set_voltage(self, voltage: int) -> KT002Reply:
        """Request a supported fixed PDO through onBoot.lua.

        This method verifies only the Lua_MOSI protocol acknowledgement. The
        calling test engine must verify actual VBUS using the electronic load or
        another trusted measurement instrument before enabling load current.
        """
        if voltage not in self.ALLOWED_VOLTAGES:
            allowed = ", ".join(str(value) for value in self.ALLOWED_VOLTAGES)
            raise ValueError(f"unsupported voltage {voltage}; allowed: {allowed}")
        return self.send_command(f"PD_{voltage}V")

    def release(self) -> KT002Reply:
        """Ask onBoot.lua to return to the 5 V fixed PDO."""
        return self.send_command("RELEASE")

    def clear_display(self) -> KT002Reply:
        """Return the KT002 display to its waiting state."""
        return self.send_command("CLEAR")


# Short alias for easier integration with the DOE6 driver factory.
KT002 = KT002Controller
