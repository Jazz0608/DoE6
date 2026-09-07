"""USB transport layer for the POWER-Z KT002 direct-USB driver.

This module owns KT002 USB discovery, interface claiming, endpoint I/O, input
draining, and resource cleanup. It contains no Shizuku frame encoding or
decoding, Lua command logic, PDO control, or high-level controller behavior.

Verified KT002 USB configuration:
    Vendor ID:       0x0483
    Product IDs:     0xFFFF, 0xFFFE, 0x374B
    USB interface:   0
    Bulk OUT:        0x01
    Bulk IN:         0x81
    Read size:       4096 bytes

KT002 is a composite USB device. The transport deliberately does not call
set_configuration(), because doing so was observed to cause Resource busy on
the Raspberry Pi when other interfaces were already active.
"""

from __future__ import annotations

from typing import Any

import usb.core
import usb.util

from drivers.kt002.constants import (
    KT002_USB_EP_IN,
    KT002_USB_EP_OUT,
    KT002_USB_INTERFACE,
    KT002_USB_PIDS,
    KT002_USB_READ_SIZE,
    KT002_USB_VID,
)
from drivers.kt002.exceptions import (
    KT002NotFoundError,
    KT002USBError,
)


DEFAULT_WRITE_TIMEOUT_MS = 2000
DEFAULT_DRAIN_TIMEOUT_MS = 50


class KT002USBTransport:
    """Manage the verified KT002 direct-USB connection.

    The class can be used directly or as a context manager::

        with KT002USBTransport() as transport:
            transport.write(packet)
            data = transport.read(timeout_ms=250)

    No Shizuku protocol interpretation is performed here. Read operations
    return raw endpoint bytes, and write operations accept already framed
    packet bytes.
    """

    VID = KT002_USB_VID
    VALID_PIDS = KT002_USB_PIDS
    INTERFACE = KT002_USB_INTERFACE
    EP_OUT = KT002_USB_EP_OUT
    EP_IN = KT002_USB_EP_IN
    READ_SIZE = KT002_USB_READ_SIZE

    def __init__(self) -> None:
        self._device: Any | None = None
        self._pid: int | None = None
        self._claimed = False
        self._detached_kernel_driver = False

    @property
    def connected(self) -> bool:
        """Return True when the KT002 USB interface is currently claimed."""
        return self._device is not None and self._claimed

    @property
    def pid(self) -> int | None:
        """Return the connected KT002 product ID, or None when disconnected."""
        return self._pid

    @property
    def device(self) -> Any | None:
        """Return the underlying PyUSB device object.

        This property exists for diagnostics and staged migration only.
        High-level driver code should normally use read(), write(), and close().
        """
        return self._device

    @classmethod
    def find_device(cls) -> tuple[Any | None, int | None]:
        """Find the first supported KT002 USB device.

        Returns:
            A tuple containing the PyUSB device and matching PID. If a KT002 is
            not found, both tuple entries are None.
        """
        for pid in cls.VALID_PIDS:
            device = usb.core.find(
                idVendor=cls.VID,
                idProduct=pid,
            )
            if device is not None:
                return device, pid

        return None, None

    def connect(self) -> "KT002USBTransport":
        """Find and claim the verified KT002 USB interface.

        Returns:
            This transport instance.

        Raises:
            KT002NotFoundError:
                If no supported KT002 is present.

            KT002USBError:
                If interface claiming or initial endpoint preparation fails.
        """
        if self.connected:
            return self

        device, pid = self.find_device()
        if device is None:
            raise KT002NotFoundError(
                "KT002 not found. Expected VID 0483 and "
                "PID FFFF/FFFE/374B."
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

            # Do not call device.set_configuration(). KT002 is a composite USB
            # device and the verified Raspberry Pi path claims interface 0
            # directly to avoid Errno 16 Resource busy.
            usb.util.claim_interface(device, self.INTERFACE)
            self._claimed = True

            for endpoint in (self.EP_OUT, self.EP_IN):
                try:
                    device.clear_halt(endpoint)
                except usb.core.USBError:
                    pass

            self.drain_input()
            return self

        except usb.core.USBError as exc:
            self.close()
            raise KT002USBError(
                f"Unable to claim KT002 interface {self.INTERFACE}: {exc}"
            ) from exc

    def close(self) -> None:
        """Release USB resources and restore the detached kernel driver."""
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

    def __enter__(self) -> "KT002USBTransport":
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def require_connected(self) -> None:
        """Raise KT002USBError unless the transport is connected."""
        if not self.connected:
            raise KT002USBError("KT002 is not connected")

    def clear_halt(self, endpoint: int) -> None:
        """Clear an endpoint halt condition.

        Args:
            endpoint:
                USB endpoint address.
        """
        self.require_connected()
        try:
            self._device.clear_halt(endpoint)
        except usb.core.USBError as exc:
            raise KT002USBError(
                f"Unable to clear KT002 endpoint 0x{endpoint:02X}: {exc}"
            ) from exc

    def drain_input(
        self,
        *,
        timeout_ms: int = DEFAULT_DRAIN_TIMEOUT_MS,
    ) -> None:
        """Discard stale packets currently queued on the bulk IN endpoint."""
        self.require_connected()

        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be greater than zero")

        while True:
            try:
                self._device.read(
                    self.EP_IN,
                    self.READ_SIZE,
                    timeout=timeout_ms,
                )
            except usb.core.USBTimeoutError:
                return
            except usb.core.USBError as exc:
                raise KT002USBError(
                    f"Unable to drain KT002 input: {exc}"
                ) from exc

    def write(
        self,
        data: bytes,
        *,
        timeout_ms: int = DEFAULT_WRITE_TIMEOUT_MS,
    ) -> int:
        """Write one already-framed packet to the KT002 bulk OUT endpoint.

        A short USB write is treated as an error rather than success.
        """
        self.require_connected()

        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes-like")
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be greater than zero")

        packet = bytes(data)
        if not packet:
            raise ValueError("data must not be empty")

        try:
            written = self._device.write(
                self.EP_OUT,
                packet,
                timeout=timeout_ms,
            )
        except usb.core.USBError as exc:
            raise KT002USBError(
                f"KT002 USB write failed: {exc}"
            ) from exc

        if written != len(packet):
            raise KT002USBError(
                f"short KT002 USB write: {written} of {len(packet)} bytes"
            )

        return written

    def read(
        self,
        *,
        timeout_ms: int,
        size: int | None = None,
    ) -> bytes:
        """Read raw bytes from the KT002 bulk IN endpoint.

        PyUSB timeout exceptions are intentionally allowed to propagate as
        usb.core.USBTimeoutError. The controller owns retry and overall timeout
        policy, while this transport converts other USB failures to
        KT002USBError.
        """
        self.require_connected()

        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be greater than zero")

        read_size = self.READ_SIZE if size is None else size
        if read_size <= 0:
            raise ValueError("size must be greater than zero")

        try:
            return bytes(
                self._device.read(
                    self.EP_IN,
                    read_size,
                    timeout=timeout_ms,
                )
            )
        except usb.core.USBTimeoutError:
            raise
        except usb.core.USBError as exc:
            raise KT002USBError(
                f"KT002 USB read failed: {exc}"
            ) from exc


__all__ = [
    "DEFAULT_WRITE_TIMEOUT_MS",
    "DEFAULT_DRAIN_TIMEOUT_MS",
    "KT002USBTransport",
]
