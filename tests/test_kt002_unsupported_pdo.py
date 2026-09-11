#!/usr/bin/env python3
"""KT002 Phase 4 unsupported Fixed PDO hardware regression.

Default sample capability used by this test:
    Supported baseline PDO: 9V
    Unsupported PDOs: 15V and 20V

For each unsupported request, the test verifies:
    - KT002PDONotFoundError is raised
    - requested_voltage is correct
    - command metadata is correct
    - raw Lua MISO text is preserved
    - no KT002PDOResult is incorrectly returned
    - Lua remains responsive after the failure

The test finishes by requesting and verifying the safe 5V Fixed PDO.

Safety requirements:
    - Verified onBoot.lua is running on KT002
    - New PD charger sample is connected and powered
    - Electronic load is disconnected or Input OFF
    - KT Toolbox is not connected
"""

from __future__ import annotations

import argparse
import time

from drivers.kt002 import (
    KT002CommandResult,
    KT002Controller,
    KT002Error,
    KT002PDONotFoundError,
    KT002PDOResult,
    KT002VoltageVerificationError,
)


DEFAULT_BASELINE_VOLTAGE = 9
DEFAULT_UNSUPPORTED_VOLTAGES = (15, 20)


def verify_supported_result(
    result: KT002PDOResult,
    *,
    expected_voltage: int,
    tolerance: float,
) -> None:
    """Verify a successful structured PDO result."""

    if not isinstance(result, KT002PDOResult):
        raise TypeError("Expected KT002PDOResult")

    if not result.success:
        raise RuntimeError("Supported PDO returned success=False")

    if result.requested_voltage != expected_voltage:
        raise RuntimeError(
            f"Expected {expected_voltage}V result, received "
            f"{result.requested_voltage}V"
        )

    if result.absolute_voltage_error > tolerance:
        raise KT002VoltageVerificationError(
            f"PD_{expected_voltage}V measured "
            f"{result.measured_voltage:.3f}V, outside "
            f"+/-{tolerance:.3f}V tolerance",
            requested_voltage=float(expected_voltage),
            measured_voltage=result.measured_voltage,
            tolerance=tolerance,
        )


def request_supported_pdo(
    controller: KT002Controller,
    voltage: int,
    *,
    timeout: float,
    tolerance: float,
) -> KT002PDOResult:
    """Request and verify a known supported Fixed PDO."""

    print()
    print(f"Requesting supported baseline PD_{voltage}V...")
    result = controller.set_voltage_result(voltage, timeout=timeout)
    verify_supported_result(
        result,
        expected_voltage=voltage,
        tolerance=tolerance,
    )

    print(f"Result type: {type(result).__name__}")
    print(f"Raw result: {result.raw_text}")
    print(f"Measured: {result.measured_voltage:.3f}V")
    print(f"PDO index: {result.pdo_index}")
    print(f"PASS: supported PD_{voltage}V established")
    return result


def verify_lua_alive(
    controller: KT002Controller,
    *,
    timeout: float,
    stage: str,
) -> None:
    """Verify that the Lua event loop still answers after a failed PDO."""

    result = controller.lua_ping_result(timeout=timeout)
    if not isinstance(result, KT002CommandResult):
        raise TypeError("lua_ping_result() did not return KT002CommandResult")
    if not result.success or result.raw_text != "PONG:KT002":
        raise RuntimeError(
            f"Unexpected Lua PING result after {stage}: {result!r}"
        )

    print(f"Lua health after {stage}: {result.raw_text}")
    print(f"PASS: Lua event loop remains active after {stage}")


def request_unsupported_pdo(
    controller: KT002Controller,
    voltage: int,
    *,
    timeout: float,
) -> KT002PDONotFoundError:
    """Require one unsupported PDO request to raise the typed exception."""

    command = f"PD_{voltage}V"
    expected_raw_text = f"ERROR:PDO_{voltage}V_NOT_FOUND"

    print()
    print(f"Requesting unsupported {command}...")

    try:
        unexpected_result = controller.set_voltage_result(
            voltage,
            timeout=timeout,
        )
    except KT002PDONotFoundError as error:
        if error.requested_voltage != voltage:
            raise RuntimeError(
                "KT002PDONotFoundError requested_voltage mismatch: "
                f"expected {voltage}, received {error.requested_voltage}"
            ) from error

        if error.command != command:
            raise RuntimeError(
                "KT002PDONotFoundError command mismatch: "
                f"expected {command!r}, received {error.command!r}"
            ) from error

        if error.raw_text != expected_raw_text:
            raise RuntimeError(
                "KT002PDONotFoundError raw_text mismatch: "
                f"expected {expected_raw_text!r}, "
                f"received {error.raw_text!r}"
            ) from error

        print(f"Exception type: {type(error).__name__}")
        print(f"requested_voltage: {error.requested_voltage}")
        print(f"command: {error.command}")
        print(f"raw_text: {error.raw_text}")
        print(f"PASS: unsupported {command} correctly rejected")
        return error

    raise RuntimeError(
        f"Unsupported {command} incorrectly returned success: "
        f"{unexpected_result!r}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="KT002 Phase 4 unsupported Fixed PDO hardware regression"
    )
    parser.add_argument(
        "--baseline",
        type=int,
        default=DEFAULT_BASELINE_VOLTAGE,
        choices=(5, 9, 12),
        help="known supported baseline PDO, default: 9V",
    )
    parser.add_argument(
        "--unsupported",
        type=int,
        nargs="+",
        default=list(DEFAULT_UNSUPPORTED_VOLTAGES),
        choices=(9, 12, 15, 20),
        help="unsupported PDO voltages, default: 15 20",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="Lua result timeout in seconds, default: 8.0",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1.0,
        help="allowed baseline and final 5V deviation, default: 1.0V",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=1.0,
        help="pause after each operation, default: 1.0 second",
    )
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.tolerance <= 0:
        parser.error("--tolerance must be greater than zero")
    if args.pause < 0:
        parser.error("--pause must not be negative")
    if args.baseline in args.unsupported:
        parser.error("baseline voltage cannot also be marked unsupported")

    unsupported_voltages = tuple(dict.fromkeys(args.unsupported))

    print("=" * 72)
    print("KT002 Phase 4 unsupported Fixed PDO regression")
    print(f"Supported baseline: {args.baseline}V")
    print(
        "Unsupported targets: "
        + ", ".join(f"{voltage}V" for voltage in unsupported_voltages)
    )
    print("Electronic load must be disconnected or Input OFF.")
    print("=" * 72)

    controller = KT002Controller(timeout=3.0)
    final_5v_confirmed = False

    try:
        controller.connect()
        print(
            f"Connected: VID={controller.VID:04X} "
            f"PID={controller.pid:04X}"
        )
        print(f"Controller: {KT002Controller.__module__}")

        protocol_reply = controller.ping()
        print(f"Protocol PING: 0x{protocol_reply.header:08X}")
        verify_lua_alive(controller, timeout=5.0, stage="initial check")

        baseline_result = request_supported_pdo(
            controller,
            args.baseline,
            timeout=args.timeout,
            tolerance=args.tolerance,
        )
        baseline_measured = baseline_result.measured_voltage

        if args.pause:
            time.sleep(args.pause)

        for voltage in unsupported_voltages:
            request_unsupported_pdo(
                controller,
                voltage,
                timeout=args.timeout,
            )

            if args.pause:
                time.sleep(args.pause)

            verify_lua_alive(
                controller,
                timeout=5.0,
                stage=f"failed PD_{voltage}V request",
            )

            print(
                "CHECK: KT002 VBUS must remain near the previous "
                f"supported state, approximately {baseline_measured:.3f}V."
            )

        print()
        print("Final safety step: requesting PD_5V...")
        final_result = controller.set_voltage_result(5, timeout=args.timeout)
        verify_supported_result(
            final_result,
            expected_voltage=5,
            tolerance=args.tolerance,
        )
        final_5v_confirmed = True

        print(f"Final result: {final_result.raw_text}")
        print(f"Final measured voltage: {final_result.measured_voltage:.3f}V")
        verify_lua_alive(controller, timeout=5.0, stage="final PD_5V")

        print()
        print("=" * 72)
        print("PASS: Phase 4 unsupported PDO regression completed")
        print("Typed KT002PDONotFoundError verified for all targets")
        print("Lua event loop remained active")
        print("Final safe 5V state confirmed")
        print("=" * 72)
        return 0

    except KeyboardInterrupt:
        print()
        print("ABORT: test interrupted by operator")
        return 130

    except (KT002Error, RuntimeError, TypeError, ValueError) as error:
        print()
        print(f"FAIL: {type(error).__name__}: {error}")
        return 1

    finally:
        if controller.connected and not final_5v_confirmed:
            print()
            print("Safety recovery: attempting PD_5V...")
            try:
                result = controller.set_voltage_result(5, timeout=args.timeout)
                verify_supported_result(
                    result,
                    expected_voltage=5,
                    tolerance=args.tolerance,
                )
                print("PASS: safety recovery returned to PD_5V")
            except Exception as error:
                print(f"WARNING: PD_5V safety recovery failed: {error}")

        controller.close()
        print("KT002 USB connection closed")


if __name__ == "__main__":
    raise SystemExit(main())
