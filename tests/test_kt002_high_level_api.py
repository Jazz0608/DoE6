#!/usr/bin/env python3
"""Offline unit tests for the KT002 Phase 3 high-level controller API.

The tests use a deterministic fake USB transport. No KT002, PD charger,
electronic load, sudo permission, or onBoot.lua runtime is required.

Run from the DOE6 repository root:
    .venv/bin/python -m unittest tests.test_kt002_high_level_api -v
"""

from __future__ import annotations

import unittest

import usb.core

from drivers.kt002 import (
    KT002CommandResult,
    KT002Controller,
    KT002PDONotFoundError,
    KT002PDORequestError,
    KT002PDOResult,
    KT002PDSourceError,
    KT002TimeoutError,
)
from drivers.kt002.protocol import pack_frame


BACKGROUND_TYPE_1 = bytes.fromhex(
    "0A 01 01 80 58 E7 00 00 50 CD 00 00 "
    "00 90 01 00 74 05 00 00 00 10 00 00"
)
BACKGROUND_TYPE_2 = bytes.fromhex("0A 02 01 80 05 00 00 00")


def reply_frame(header: int, body: bytes = b"") -> bytes:
    """Build one valid Shizuku reply frame for the fake transport."""

    return pack_frame(header.to_bytes(4, "little") + body)


def text_report(text: str) -> bytes:
    """Build one verified Type 0x10 Lua MISO text Report."""

    return reply_frame(0x8001100A, text.encode("utf-8"))


class FakeKT002Transport:
    """Minimal deterministic transport used by offline controller tests."""

    VID = 0x0483
    VALID_PIDS = (0xFFFF, 0xFFFE, 0x374B)
    INTERFACE = 0
    EP_OUT = 0x01
    EP_IN = 0x81
    READ_SIZE = 4096

    def __init__(
        self,
        *,
        command_results: dict[str, str] | None = None,
        text_before_ack: bool = False,
        omit_setup_ack: bool = False,
        omit_command_ack: bool = False,
    ) -> None:
        self._connected = False
        self._pid: int | None = None
        self._queue: list[bytes] = []
        self.command_results = dict(command_results or {})
        self.text_before_ack = text_before_ack
        self.omit_setup_ack = omit_setup_ack
        self.omit_command_ack = omit_command_ack
        self.writes: list[bytes] = []
        self.drain_count = 0
        self.close_count = 0

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def pid(self) -> int | None:
        return self._pid

    def connect(self) -> "FakeKT002Transport":
        self._connected = True
        self._pid = 0xFFFF
        return self

    def close(self) -> None:
        self._connected = False
        self._pid = None
        self._queue.clear()
        self.close_count += 1

    def drain_input(self, *, timeout_ms: int = 50) -> None:
        if not self.connected:
            raise RuntimeError("fake transport is not connected")
        self._queue.clear()
        self.drain_count += 1

    def write(self, data: bytes, *, timeout_ms: int = 2000) -> int:
        if not self.connected:
            raise RuntimeError("fake transport is not connected")

        packet = bytes(data)
        self.writes.append(packet)
        payload_length = int.from_bytes(packet[1:5], "little")
        payload = packet[5:5 + payload_length]
        request_header = int.from_bytes(payload[:4], "little")
        caller_id = (request_header >> 16) & 0xFFFF
        request_type = (request_header >> 8) & 0xFF

        if request_type == 0x10 and caller_id == 1:
            self._queue.extend(
                (pack_frame(BACKGROUND_TYPE_1), pack_frame(BACKGROUND_TYPE_2))
            )
            if not self.omit_setup_ack:
                self._queue.append(reply_frame(0x80010003))
            self._queue.append(text_report("READY:KT002_FIXED_PDO\n"))
            return len(packet)

        if request_type == 0x08:
            self._queue.extend(
                (
                    pack_frame(BACKGROUND_TYPE_1),
                    pack_frame(BACKGROUND_TYPE_2),
                    reply_frame(0x80000009),
                )
            )
            return len(packet)

        if request_type == 0x1F:
            argument_header = int.from_bytes(payload[4:8], "little")
            content_length = argument_header >> 16
            command = payload[8:8 + content_length].decode("utf-8")
            result = self.command_results.get(command)

            frames: list[bytes] = [
                pack_frame(BACKGROUND_TYPE_1),
                pack_frame(BACKGROUND_TYPE_2),
            ]
            if result is not None and self.text_before_ack:
                frames.append(text_report(result + "\n"))
            if not self.omit_command_ack:
                frames.append(reply_frame(0x80000000))
            if result is not None and not self.text_before_ack:
                frames.append(text_report(result + "\n"))

            self._queue.extend(frames)
            return len(packet)

        raise AssertionError(f"Unexpected request type 0x{request_type:02X}")

    def read(self, *, timeout_ms: int, size: int | None = None) -> bytes:
        if not self.connected:
            raise RuntimeError("fake transport is not connected")
        if self._queue:
            return self._queue.pop(0)
        raise usb.core.USBTimeoutError("fake timeout")


class TestKT002HighLevelPing(unittest.TestCase):
    """Verify protocol PING and structured Lua PING behavior."""

    def test_protocol_ping_ignores_background_reports(self) -> None:
        transport = FakeKT002Transport()
        with KT002Controller(transport=transport) as controller:
            reply = controller.ping()

        self.assertEqual(reply.header, 0x80000009)
        self.assertFalse(transport.connected)

    def test_lua_ping_result_returns_structured_model(self) -> None:
        transport = FakeKT002Transport(
            command_results={"PING": "PONG:KT002"}
        )
        with KT002Controller(transport=transport) as controller:
            result = controller.lua_ping_result()

        self.assertIsInstance(result, KT002CommandResult)
        self.assertTrue(result.success)
        self.assertEqual(result.command, "PING")
        self.assertEqual(result.raw_text, "PONG:KT002")
        self.assertEqual(result.message, "KT002 Lua controller is online")

    def test_lua_ping_accepts_text_before_ack(self) -> None:
        transport = FakeKT002Transport(
            command_results={"PING": "PONG:KT002"},
            text_before_ack=True,
        )
        with KT002Controller(transport=transport) as controller:
            result = controller.lua_ping_result()

        self.assertEqual(result.raw_text, "PONG:KT002")

    def test_miso_registration_occurs_only_once_per_connection(self) -> None:
        transport = FakeKT002Transport(
            command_results={"PING": "PONG:KT002"}
        )
        with KT002Controller(transport=transport) as controller:
            controller.lua_ping_result()
            controller.lua_ping_result()

        setup_writes = []
        for packet in transport.writes:
            payload_length = int.from_bytes(packet[1:5], "little")
            payload = packet[5:5 + payload_length]
            header = int.from_bytes(payload[:4], "little")
            if ((header >> 8) & 0xFF) == 0x10:
                setup_writes.append(packet)

        self.assertEqual(len(setup_writes), 1)


class TestKT002HighLevelPDO(unittest.TestCase):
    """Verify structured Fixed PDO results and typed failures."""

    def test_set_voltage_result_returns_structured_pdo_result(self) -> None:
        transport = FakeKT002Transport(
            command_results={"PD_9V": "OK:PD_9V:8.932V:PDO=1"}
        )
        with KT002Controller(transport=transport) as controller:
            result = controller.set_voltage_result(9)

        self.assertIsInstance(result, KT002PDOResult)
        self.assertEqual(result.requested_voltage, 9)
        self.assertAlmostEqual(result.measured_voltage, 8.932, places=3)
        self.assertEqual(result.pdo_index, 1)
        self.assertAlmostEqual(result.absolute_voltage_error, 0.068, places=3)

    def test_all_verified_fixed_pdo_results(self) -> None:
        expected = {
            5: "OK:PD_5V:5.115V:PDO=0",
            9: "OK:PD_9V:8.929V:PDO=1",
            12: "OK:PD_12V:11.974V:PDO=2",
            15: "OK:PD_15V:15.016V:PDO=3",
            20: "OK:PD_20V:20.224V:PDO=4",
        }
        transport = FakeKT002Transport(
            command_results={f"PD_{voltage}V": text for voltage, text in expected.items()}
        )

        with KT002Controller(transport=transport) as controller:
            for voltage in (5, 9, 12, 15, 20):
                with self.subTest(voltage=voltage):
                    result = controller.set_voltage_result(voltage)
                    self.assertEqual(result.requested_voltage, voltage)
                    self.assertEqual(result.raw_text, expected[voltage])

    def test_pdo_not_found_becomes_typed_exception(self) -> None:
        transport = FakeKT002Transport(
            command_results={"PD_12V": "ERROR:PDO_12V_NOT_FOUND"}
        )
        with KT002Controller(transport=transport) as controller:
            with self.assertRaises(KT002PDONotFoundError) as context:
                controller.set_voltage_result(12)

        self.assertEqual(context.exception.requested_voltage, 12)
        self.assertEqual(context.exception.command, "PD_12V")

    def test_pdo_request_failure_becomes_typed_exception(self) -> None:
        transport = FakeKT002Transport(
            command_results={
                "PD_9V": "ERROR:REQUEST_FAILED:PD_9V:PDO=1"
            }
        )
        with KT002Controller(transport=transport) as controller:
            with self.assertRaises(KT002PDORequestError) as context:
                controller.set_voltage_result(9)

        self.assertEqual(context.exception.requested_voltage, 9)
        self.assertEqual(context.exception.pdo_index, 1)

    def test_no_pd_source_becomes_typed_exception(self) -> None:
        transport = FakeKT002Transport(
            command_results={"PD_9V": "ERROR:NO_PD_SOURCE"}
        )
        with KT002Controller(transport=transport) as controller:
            with self.assertRaises(KT002PDSourceError):
                controller.set_voltage_result(9)

    def test_unsupported_voltage_is_rejected_before_usb_write(self) -> None:
        transport = FakeKT002Transport()
        with KT002Controller(transport=transport) as controller:
            with self.assertRaises(ValueError):
                controller.set_voltage_result(11)

        self.assertEqual(transport.writes, [])


class TestKT002HighLevelTimeouts(unittest.TestCase):
    """Verify missing setup, ACK, and result handling."""

    def test_missing_setup_ack_times_out(self) -> None:
        transport = FakeKT002Transport(
            command_results={"PING": "PONG:KT002"},
            omit_setup_ack=True,
        )
        with KT002Controller(transport=transport) as controller:
            with self.assertRaises(KT002TimeoutError):
                controller.lua_ping_result(timeout=0.01)

    def test_missing_command_ack_times_out(self) -> None:
        transport = FakeKT002Transport(
            command_results={"PING": "PONG:KT002"},
            omit_command_ack=True,
        )
        with KT002Controller(transport=transport) as controller:
            with self.assertRaises(KT002TimeoutError) as context:
                controller.lua_ping_result(timeout=0.01)

        self.assertIn("ACK", str(context.exception))

    def test_missing_lua_result_times_out(self) -> None:
        transport = FakeKT002Transport(command_results={})
        with KT002Controller(transport=transport) as controller:
            with self.assertRaises(KT002TimeoutError):
                controller.lua_ping_result(timeout=0.01)


class TestKT002PhaseCompatibility(unittest.TestCase):
    """Verify that Phase 1, Phase 2, and Phase 3 APIs coexist."""

    def test_phase_1_lua_ping_returns_protocol_ack(self) -> None:
        transport = FakeKT002Transport(
            command_results={"PING": "PONG:KT002"}
        )
        with KT002Controller(transport=transport) as controller:
            reply = controller.lua_ping()

        self.assertEqual(reply.header, 0x80000000)

    def test_phase_2_lua_ping_returns_text(self) -> None:
        transport = FakeKT002Transport(
            command_results={"PING": "PONG:KT002"}
        )
        with KT002Controller(transport=transport) as controller:
            result = controller.lua_ping_wait_result()

        self.assertEqual(result, "PONG:KT002")

    def test_phase_2_set_voltage_returns_text(self) -> None:
        transport = FakeKT002Transport(
            command_results={"PD_9V": "OK:PD_9V:8.932V:PDO=1"}
        )
        with KT002Controller(transport=transport) as controller:
            result = controller.set_voltage_wait_result(9)

        self.assertEqual(result, "OK:PD_9V:8.932V:PDO=1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
