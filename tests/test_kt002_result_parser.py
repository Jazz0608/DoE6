#!/usr/bin/env python3
"""Offline unit tests for the KT002 Phase 3 Lua MISO result parser.

This test module does not access USB hardware and does not require a KT002,
PD charger, electronic load, or onBoot.lua runtime.

Run from the DOE6 repository root:
    .venv/bin/python -m unittest tests.test_kt002_result_parser -v
"""

from __future__ import annotations

import unittest

from drivers.kt002 import (
    KT002CommandResult,
    KT002LuaError,
    KT002PDONotFoundError,
    KT002PDORequestError,
    KT002PDOResult,
    KT002PDSourceError,
    normalize_command,
    normalize_lua_line,
    parse_lua_result,
    parse_pdo_result,
    raise_for_lua_error,
)


class TestKT002Normalization(unittest.TestCase):
    """Verify Lua response and command normalization."""

    def test_normalize_lua_line_removes_outer_whitespace(self) -> None:
        self.assertEqual(
            normalize_lua_line("  OK:PD_9V:8.932V:PDO=1\r\n"),
            "OK:PD_9V:8.932V:PDO=1",
        )

    def test_normalize_lua_line_rejects_non_string(self) -> None:
        with self.assertRaises(TypeError):
            normalize_lua_line(b"PONG:KT002")  # type: ignore[arg-type]

    def test_normalize_lua_line_rejects_empty_text(self) -> None:
        with self.assertRaises(ValueError):
            normalize_lua_line("  \r\n  ")

    def test_normalize_command_uppercases_and_strips(self) -> None:
        self.assertEqual(normalize_command("  pd_9v  "), "PD_9V")

    def test_normalize_command_accepts_none(self) -> None:
        self.assertIsNone(normalize_command(None))

    def test_normalize_command_rejects_empty_command(self) -> None:
        with self.assertRaises(ValueError):
            normalize_command("   ")


class TestKT002SuccessfulResults(unittest.TestCase):
    """Verify successful Lua MISO response parsing."""

    def test_parse_pdo_9v_result(self) -> None:
        result = parse_pdo_result("OK:PD_9V:8.932V:PDO=1")

        self.assertIsInstance(result, KT002PDOResult)
        self.assertTrue(result.success)
        self.assertEqual(result.requested_voltage, 9)
        self.assertAlmostEqual(result.measured_voltage, 8.932, places=3)
        self.assertEqual(result.pdo_index, 1)
        self.assertEqual(result.raw_text, "OK:PD_9V:8.932V:PDO=1")
        self.assertAlmostEqual(result.voltage_error, -0.068, places=3)
        self.assertAlmostEqual(result.absolute_voltage_error, 0.068, places=3)

    def test_parse_all_verified_fixed_pdo_results(self) -> None:
        cases = (
            ("OK:PD_5V:5.115V:PDO=0", 5, 5.115, 0),
            ("OK:PD_9V:8.929V:PDO=1", 9, 8.929, 1),
            ("OK:PD_12V:11.974V:PDO=2", 12, 11.974, 2),
            ("OK:PD_15V:15.016V:PDO=3", 15, 15.016, 3),
            ("OK:PD_20V:20.224V:PDO=4", 20, 20.224, 4),
        )

        for raw_text, voltage, measured, pdo_index in cases:
            with self.subTest(voltage=voltage):
                result = parse_lua_result(
                    raw_text,
                    command=f"PD_{voltage}V",
                )
                self.assertIsInstance(result, KT002PDOResult)
                self.assertEqual(result.requested_voltage, voltage)
                self.assertAlmostEqual(
                    result.measured_voltage,
                    measured,
                    places=3,
                )
                self.assertEqual(result.pdo_index, pdo_index)

    def test_parse_ping_result(self) -> None:
        result = parse_lua_result("PONG:KT002", command="PING")

        self.assertIsInstance(result, KT002CommandResult)
        self.assertTrue(result.success)
        self.assertEqual(result.command, "PING")
        self.assertEqual(result.raw_text, "PONG:KT002")
        self.assertEqual(result.message, "KT002 Lua controller is online")
        self.assertIsNone(result.data)

    def test_parse_ready_result(self) -> None:
        result = parse_lua_result("READY:KT002_FIXED_PDO")

        self.assertIsInstance(result, KT002CommandResult)
        self.assertTrue(result.success)
        self.assertEqual(result.command, "STARTUP")
        self.assertEqual(result.message, "KT002 Lua controller is ready")

    def test_parse_pd_initialized_result(self) -> None:
        result = parse_lua_result(
            "OK:PD_INITIALIZED:5",
            command="INIT",
        )

        self.assertIsInstance(result, KT002CommandResult)
        self.assertTrue(result.success)
        self.assertEqual(result.command, "INIT")
        self.assertEqual(result.data, {"source_capability_count": 5})

    def test_parse_generic_ok_result(self) -> None:
        result = parse_lua_result("OK:CLEAR", command="CLEAR")

        self.assertIsInstance(result, KT002CommandResult)
        self.assertTrue(result.success)
        self.assertEqual(result.command, "CLEAR")
        self.assertEqual(result.message, "CLEAR")


class TestKT002TypedErrors(unittest.TestCase):
    """Verify that Lua ERROR lines become typed exceptions."""

    def test_non_error_line_returns_normally(self) -> None:
        self.assertIsNone(
            raise_for_lua_error("PONG:KT002", command="PING")
        )

    def test_pdo_not_found_error(self) -> None:
        with self.assertRaises(KT002PDONotFoundError) as context:
            parse_lua_result(
                "ERROR:PDO_12V_NOT_FOUND",
                command="PD_12V",
            )

        error = context.exception
        self.assertEqual(error.requested_voltage, 12)
        self.assertEqual(error.command, "PD_12V")
        self.assertEqual(error.raw_text, "ERROR:PDO_12V_NOT_FOUND")

    def test_pdo_request_failed_error(self) -> None:
        with self.assertRaises(KT002PDORequestError) as context:
            parse_lua_result(
                "ERROR:REQUEST_FAILED:PD_9V:PDO=1",
                command="PD_9V",
            )

        error = context.exception
        self.assertEqual(error.requested_voltage, 9)
        self.assertEqual(error.pdo_index, 1)
        self.assertEqual(error.command, "PD_9V")
        self.assertEqual(
            error.raw_text,
            "ERROR:REQUEST_FAILED:PD_9V:PDO=1",
        )

    def test_all_known_pd_source_errors(self) -> None:
        errors = (
            "ERROR:NO_PD_SOURCE",
            "ERROR:SOURCE_CAP_TIMEOUT",
            "ERROR:NO_SOURCE_CAPABILITY",
            "ERROR:FASTCHG_OPEN_FAILED",
        )

        for raw_text in errors:
            with self.subTest(raw_text=raw_text):
                with self.assertRaises(KT002PDSourceError) as context:
                    parse_lua_result(raw_text, command="PD_9V")

                self.assertEqual(context.exception.raw_text, raw_text)
                self.assertEqual(context.exception.command, "PD_9V")

    def test_lua_runtime_error(self) -> None:
        with self.assertRaises(KT002LuaError) as context:
            parse_lua_result(
                "ERROR:LUA:attempt to index a nil value",
                command="PING",
            )

        error = context.exception
        self.assertEqual(str(error), "attempt to index a nil value")
        self.assertEqual(
            error.raw_text,
            "ERROR:LUA:attempt to index a nil value",
        )
        self.assertEqual(error.command, "PING")

    def test_unknown_command_error(self) -> None:
        with self.assertRaises(KT002LuaError) as context:
            parse_lua_result(
                "ERROR:UNKNOWN_COMMAND:CAPS",
                command="CAPS",
            )

        self.assertEqual(context.exception.command, "CAPS")
        self.assertIn("CAPS", str(context.exception))

    def test_generic_lua_error(self) -> None:
        with self.assertRaises(KT002LuaError) as context:
            parse_lua_result(
                "ERROR:UNEXPECTED_FAILURE",
                command="PING",
            )

        self.assertEqual(
            context.exception.raw_text,
            "ERROR:UNEXPECTED_FAILURE",
        )


class TestKT002InvalidResults(unittest.TestCase):
    """Verify malformed and inconsistent response rejection."""

    def test_parse_pdo_result_rejects_invalid_format(self) -> None:
        invalid_results = (
            "OK:PD_9V",
            "OK:PD_9V:8.932:PDO=1",
            "OK:PD_9V:8.932V",
            "OK:PD_9V:8.932V:PDO=X",
            "OK:PD_11V:10.900V:PDO=2",
        )

        for raw_text in invalid_results:
            with self.subTest(raw_text=raw_text):
                with self.assertRaises(KT002LuaError):
                    parse_pdo_result(raw_text)

    def test_rejects_mismatched_pdo_command(self) -> None:
        with self.assertRaises(KT002LuaError) as context:
            parse_lua_result(
                "OK:PD_12V:11.974V:PDO=2",
                command="PD_9V",
            )

        self.assertEqual(context.exception.command, "PD_9V")
        self.assertEqual(
            context.exception.raw_text,
            "OK:PD_12V:11.974V:PDO=2",
        )

    def test_rejects_unrecognized_non_error_result(self) -> None:
        with self.assertRaises(KT002LuaError) as context:
            parse_lua_result("RX: PING", command="PING")

        self.assertEqual(context.exception.raw_text, "RX: PING")
        self.assertEqual(context.exception.command, "PING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
