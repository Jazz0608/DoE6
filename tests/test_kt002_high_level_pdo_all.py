#!/usr/bin/env python3
"""KT002 Phase 3 full Fixed PDO high-level API hardware regression.

Verified sequence:
    Protocol PING
    Structured Lua PING result
    5V -> 9V -> 12V -> 15V -> 20V -> 5V

Every PDO transition uses KT002Controller.set_voltage_result() and must return
KT002PDOResult. The test verifies the requested voltage, KT002 measured voltage,
PDO index, absolute voltage tolerance, final 5V safety state, and USB cleanup.

Safety requirements:
    - Verified onBoot.lua is running on KT002
    - Supported PD charger is connected and powered
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
    KT002PDOResult,
    KT002VoltageVerificationError,
)


PDO_SEQUENCE = (5, 9, 12, 15, 20)
EXPECTED_PDO_INDEX = {
    5: 0,
    9: 1,
    12: 2,
    15: 3,
    20: 4,
}


def verify_pdo_result(
    result: KT002PDOResult,
    *,
    expected_voltage: int,
    tolerance: float,
    verify_pdo_index: bool,
) -> None:
    """Validate one structured PDO result."""

    if not isinstance(result, KT002PDOResult):
        raise TypeError(
            "set_voltage_result() did not return KT002PDOResult"
        )

    if not result.success:
        raise RuntimeError(
            f"PD_{expected_voltage}V result reported success=False"
        )

    if result.requested_voltage != expected_voltage:
        raise RuntimeError(
            f"Requested {expected_voltage}V but result reported "
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

    if verify_pdo_index:
        expected_index = EXPECTED_PDO_INDEX[expected_voltage]
        if result.pdo_index != expected_index:
            raise RuntimeError(
                f"PD_{expected_voltage}V used PDO {result.pdo_index}, "
                f"expected PDO {expected_index}"
            )


def request_and_verify(
    controller: KT002Controller,
    voltage: int,
    *,
    timeout: float,
    tolerance: float,
    verify_pdo_index: bool,
) -> KT002PDOResult:
    """Request one Fixed PDO through the Phase 3 high-level API."""

    print()
    print(f"Requesting PD_{voltage}V with set_voltage_result()...")

    result = controller.set_voltage_result(
        voltage,
        timeout=timeout,
    )

    verify_pdo_result(
        result,
        expected_voltage=voltage,
        tolerance=tolerance,
        verify_pdo_index=verify_pdo_index,
    )

    print(f"Result type: {type(result).__name__}")
    print(f"Raw result: {result.raw_text}")
    print(f"Requested: {result.requested_voltage}V")
    print(f"Measured: {result.measured_voltage:.3f}V")
    print(f"PDO index: {result.pdo_index}")
    print(f"Voltage error: {result.voltage_error:+.3f}V")
    print(
        f"PASS: PD_{voltage}V structured result verified, "
        f"deviation={result.absolute_voltage_error:.3f}V"
    )

    return result


def attempt_safe_5v(
    controller: KT002Controller,
    *,
    timeout: float,
    tolerance: float,
    verify_pdo_index: bool,
) -> bool:
    """Attempt to restore the verified 5V Fixed PDO after a failure."""

    if not controller.connected:
        return False

    print()
    print("Safety action: attempting high-level return to PD_5V...")

    try:
        request_and_verify(
            controller,
            5,
            timeout=timeout,
            tolerance=tolerance,
            verify_pdo_index=verify_pdo_index,
        )
        return True
    except Exception as error:
        print(f"WARNING: unable to confirm safe 5V state: {error}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "KT002 Phase 3 full Fixed PDO high-level API hardware regression"
        )
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="Lua MISO result timeout per PDO, default: 8.0 seconds",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1.0,
        help="allowed absolute voltage deviation, default: 1.0V",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=1.0,
        help="pause between PDO requests, default: 1.0 second",
    )
    parser.add_argument(
        "--skip-pdo-index-check",
        action="store_true",
        help=(
            "do not require the verified PDO indexes 0,1,2,3,4; use this "
            "only when testing a charger with a different capability order"
        ),
    )
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.tolerance <= 0:
        parser.error("--tolerance must be greater than zero")
    if args.pause < 0:
        parser.error("--pause must not be negative")

    verify_pdo_index = not args.skip_pdo_index_check

    print("=" * 72)
    print("KT002 Phase 3 full Fixed PDO high-level API regression")
    print("Sequence: 5V -> 9V -> 12V -> 15V -> 20V -> 5V")
    print("API: lua_ping_result() and set_voltage_result()")
    print("Electronic load must be disconnected or Input OFF.")
    print(
        "PDO index verification: "
        + ("enabled" if verify_pdo_index else "disabled")
    )
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

        if KT002Controller.__module__ != "drivers.kt002.controller":
            raise RuntimeError(
                "Modular controller is not active: "
                f"{KT002Controller.__module__}"
            )

        protocol_reply = controller.ping()
        print(f"Protocol PING: 0x{protocol_reply.header:08X}")

        ping_result = controller.lua_ping_result(timeout=5.0)
        if not isinstance(ping_result, KT002CommandResult):
            raise TypeError(
                "lua_ping_result() did not return KT002CommandResult"
            )
        if not ping_result.success or ping_result.raw_text != "PONG:KT002":
            raise RuntimeError(
                f"Unexpected structured PING result: {ping_result!r}"
            )

        print(f"PING result type: {type(ping_result).__name__}")
        print(f"Lua PING raw result: {ping_result.raw_text}")
        print("PASS: structured Protocol and Lua PING")

        for voltage in PDO_SEQUENCE:
            request_and_verify(
                controller,
                voltage,
                timeout=args.timeout,
                tolerance=args.tolerance,
                verify_pdo_index=verify_pdo_index,
            )
            if args.pause:
                time.sleep(args.pause)

        print()
        print("Final safety step: return to PD_5V")
        request_and_verify(
            controller,
            5,
            timeout=args.timeout,
            tolerance=args.tolerance,
            verify_pdo_index=verify_pdo_index,
        )
        final_5v_confirmed = True

        print()
        print("=" * 72)
        print("PASS: Phase 3 full Fixed PDO high-level API regression")
        print("Verified: 5V -> 9V -> 12V -> 15V -> 20V -> 5V")
        print("All PDO calls returned KT002PDOResult")
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
            attempt_safe_5v(
                controller,
                timeout=args.timeout,
                tolerance=args.tolerance,
                verify_pdo_index=verify_pdo_index,
            )

        controller.close()
        print("KT002 USB connection closed")


if __name__ == "__main__":
    raise SystemExit(main())
