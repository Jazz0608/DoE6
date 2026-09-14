#!/usr/bin/env python3
"""KT002 Phase 5 Charger A to Charger B capability refresh regression.

Default test assumptions:
    Charger A supports 20V.
    Charger B does not support 20V but does support 9V.

Test sequence:
    1. Verify Protocol PING and Lua PING with Charger A connected.
    2. Request 20V from Charger A and require KT002PDOResult success.
    3. Return Charger A to 5V before physical removal.
    4. Prompt the operator to remove Charger A.
    5. Verify Lua remains alive while no charger is attached.
    6. Prompt the operator to connect Charger B.
    7. Request 20V from Charger B and require KT002PDONotFoundError.
    8. Verify the error metadata and Lua event-loop health.
    9. Request 9V from Charger B and require a fresh successful result.
   10. Return Charger B to 5V and close the KT002 USB connection.

Safety requirements:
    - Verified onBoot.lua is running on KT002.
    - KT002 PC USB remains connected to Raspberry Pi for the entire test.
    - Electronic load is disconnected or Input OFF.
    - KT Toolbox is not connected.
    - Only the charger-side Type-C connection is changed when prompted.

The script does not restart Raspberry Pi, reconnect KT002 PC USB, or rerun
onBoot.lua. A successful run therefore verifies recovery within one continuous
KT002 Lua and USB session.
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


DEFAULT_A_TEST_VOLTAGE = 20
DEFAULT_B_SUPPORTED_VOLTAGE = 9


def require_operator_token(prompt: str, expected: str) -> None:
    """Require an explicit operator token before continuing."""

    entered = input(prompt).strip().upper()
    if entered != expected.upper():
        raise RuntimeError(
            f"Operator confirmation failed: expected {expected!r}, "
            f"received {entered!r}"
        )


def verify_lua_alive(
    controller: KT002Controller,
    *,
    timeout: float,
    stage: str,
) -> KT002CommandResult:
    """Require the running Lua event loop to answer PONG:KT002."""

    result = controller.lua_ping_result(timeout=timeout)
    if not isinstance(result, KT002CommandResult):
        raise TypeError("lua_ping_result() did not return KT002CommandResult")
    if not result.success or result.raw_text != "PONG:KT002":
        raise RuntimeError(
            f"Unexpected Lua PING during {stage}: {result!r}"
        )

    print(f"Lua health during {stage}: {result.raw_text}")
    print(f"PASS: Lua event loop active during {stage}")
    return result


def verify_pdo_result(
    result: KT002PDOResult,
    *,
    expected_voltage: int,
    tolerance: float,
) -> None:
    """Validate one successful structured PDO result."""

    if not isinstance(result, KT002PDOResult):
        raise TypeError("Expected KT002PDOResult")
    if not result.success:
        raise RuntimeError("PDO result reported success=False")
    if result.requested_voltage != expected_voltage:
        raise RuntimeError(
            f"Expected {expected_voltage}V, result reported "
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
    label: str,
) -> KT002PDOResult:
    """Request and verify a known supported Fixed PDO."""

    print()
    print(f"{label}: requesting PD_{voltage}V...")
    result = controller.set_voltage_result(voltage, timeout=timeout)
    verify_pdo_result(
        result,
        expected_voltage=voltage,
        tolerance=tolerance,
    )

    print(f"Result type: {type(result).__name__}")
    print(f"Raw result: {result.raw_text}")
    print(f"Measured: {result.measured_voltage:.3f}V")
    print(f"PDO index: {result.pdo_index}")
    print(f"PASS: {label} PD_{voltage}V verified")
    return result


def wait_for_lua_after_swap(
    controller: KT002Controller,
    *,
    recovery_timeout: float,
    retry_interval: float,
) -> None:
    """Wait until Lua communication is responsive after Charger B insertion."""

    deadline = time.monotonic() + recovery_timeout
    attempt = 0
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        attempt += 1
        try:
            verify_lua_alive(
                controller,
                timeout=5.0,
                stage=f"Charger B connection attempt {attempt}",
            )
            return
        except KT002Error as error:
            last_error = error
            remaining = max(0.0, deadline - time.monotonic())
            print(
                f"Charger B is not ready on attempt {attempt}: "
                f"{type(error).__name__}: {error}"
            )
            if remaining <= 0:
                break
            time.sleep(min(retry_interval, remaining))

    raise RuntimeError(
        "Lua communication did not recover after Charger B insertion; "
        f"last error: {last_error!r}"
    )


def verify_b_rejects_a_capability(
    controller: KT002Controller,
    voltage: int,
    *,
    timeout: float,
) -> KT002PDONotFoundError:
    """Require Charger B to reject Charger A's unsupported capability."""

    command = f"PD_{voltage}V"
    expected_raw = f"ERROR:PDO_{voltage}V_NOT_FOUND"

    print()
    print(
        f"Charger B capability-refresh check: requesting {command}..."
    )
    started = time.monotonic()

    try:
        unexpected = controller.set_voltage_result(voltage, timeout=timeout)
    except KT002PDONotFoundError as error:
        elapsed = time.monotonic() - started

        if error.requested_voltage != voltage:
            raise RuntimeError(
                "requested_voltage mismatch: "
                f"expected {voltage}, received {error.requested_voltage}"
            ) from error
        if error.command != command:
            raise RuntimeError(
                "command mismatch: "
                f"expected {command!r}, received {error.command!r}"
            ) from error
        raw_text_is_valid = (
            error.raw_text == expected_raw
            or (
                isinstance(error.raw_text, str)
                and "Request: No specified PDO." in error.raw_text
            )
        )
        if not raw_text_is_valid:
            raise RuntimeError(
                "Unexpected Charger B PDO rejection text: "
                f"{error.raw_text!r}"
            ) from error

        print(f"Exception type: {type(error).__name__}")
        print(f"requested_voltage: {error.requested_voltage}")
        print(f"command: {error.command}")
        print(f"raw_text: {error.raw_text}")
        print(f"Failure latency: {elapsed:.3f}s")
        print(
            "PASS: Charger B rejected Charger A's unsupported capability"
        )
        print("PASS: Charger A PDO capability was not reused")
        return error

    raise RuntimeError(
        f"Charger B unexpectedly accepted {command}: {unexpected!r}. "
        "Verify that Charger B is the Phase 4 sample that does not support "
        f"{voltage}V."
    )


def attempt_safe_5v(
    controller: KT002Controller,
    *,
    timeout: float,
    tolerance: float,
) -> bool:
    """Attempt to restore the verified safe 5V state."""

    if not controller.connected:
        return False

    print()
    print("Safety recovery: attempting PD_5V...")
    try:
        result = controller.set_voltage_result(5, timeout=timeout)
        verify_pdo_result(
            result,
            expected_voltage=5,
            tolerance=tolerance,
        )
        print(f"Safety result: {result.raw_text}")
        print("PASS: safety recovery returned to PD_5V")
        return True
    except Exception as error:
        print(f"WARNING: PD_5V safety recovery failed: {error}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "KT002 Phase 5 Charger A to Charger B capability-refresh "
            "hardware regression"
        )
    )
    parser.add_argument(
        "--a-voltage",
        type=int,
        default=DEFAULT_A_TEST_VOLTAGE,
        choices=(9, 12, 15, 20),
        help=(
            "PDO supported by Charger A and unsupported by Charger B, "
            "default: 20V"
        ),
    )
    parser.add_argument(
        "--b-supported-voltage",
        type=int,
        default=DEFAULT_B_SUPPORTED_VOLTAGE,
        choices=(5, 9, 12, 15, 20),
        help="known supported Charger B PDO, default: 9V",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=15.0,
        help="Lua result timeout per PDO request, default: 15 seconds",
    )
    parser.add_argument(
        "--recovery-timeout",
        type=float,
        default=45.0,
        help="Charger B connection recovery window, default: 45 seconds",
    )
    parser.add_argument(
        "--retry-interval",
        type=float,
        default=2.0,
        help="delay between recovery checks, default: 2 seconds",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1.0,
        help="allowed absolute voltage deviation, default: 1.0V",
    )
    args = parser.parse_args()

    if args.a_voltage == args.b_supported_voltage:
        parser.error(
            "--a-voltage and --b-supported-voltage must be different"
        )
    if args.request_timeout <= 0:
        parser.error("--request-timeout must be greater than zero")
    if args.recovery_timeout <= 0:
        parser.error("--recovery-timeout must be greater than zero")
    if args.retry_interval <= 0:
        parser.error("--retry-interval must be greater than zero")
    if args.tolerance <= 0:
        parser.error("--tolerance must be greater than zero")

    print("=" * 72)
    print("KT002 Phase 5 Charger A to Charger B swap regression")
    print(
        f"Charger A must support {args.a_voltage}V; "
        f"Charger B must reject {args.a_voltage}V"
    )
    print(
        f"Charger B must support {args.b_supported_voltage}V for recovery"
    )
    print("Keep KT002 PC USB connected for the entire test.")
    print("Electronic load must be disconnected or Input OFF.")
    print("=" * 72)

    controller = KT002Controller(timeout=3.0)
    charger_b_connected = False
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
        verify_lua_alive(
            controller,
            timeout=5.0,
            stage="initial Charger A check",
        )

        charger_a_result = request_supported_pdo(
            controller,
            args.a_voltage,
            timeout=args.request_timeout,
            tolerance=args.tolerance,
            label="Charger A capability",
        )

        request_supported_pdo(
            controller,
            5,
            timeout=args.request_timeout,
            tolerance=args.tolerance,
            label="Charger A pre-removal safety",
        )

        print()
        print("CHARGER A REMOVAL STEP")
        print("Unplug only Charger A from the KT002 Type-C port.")
        print("Do not unplug KT002 PC USB from Raspberry Pi.")
        require_operator_token(
            "After Charger A is fully removed, type A_REMOVED: ",
            "A_REMOVED",
        )

        verify_lua_alive(
            controller,
            timeout=5.0,
            stage="no-charger interval after Charger A removal",
        )

        print()
        print("CHARGER B INSERTION STEP")
        print(
            "Connect Charger B, the Phase 4 sample that rejects "
            f"{args.a_voltage}V."
        )
        require_operator_token(
            "After Charger B is fully connected, type B_CONNECTED: ",
            "B_CONNECTED",
        )
        charger_b_connected = True

        wait_for_lua_after_swap(
            controller,
            recovery_timeout=args.recovery_timeout,
            retry_interval=args.retry_interval,
        )

        rejection = verify_b_rejects_a_capability(
            controller,
            args.a_voltage,
            timeout=args.request_timeout,
        )
        verify_lua_alive(
            controller,
            timeout=5.0,
            stage=f"Charger B rejected PD_{args.a_voltage}V",
        )

        charger_b_result = request_supported_pdo(
            controller,
            args.b_supported_voltage,
            timeout=args.request_timeout,
            tolerance=args.tolerance,
            label="Charger B supported capability",
        )
        verify_lua_alive(
            controller,
            timeout=5.0,
            stage="Charger B supported PDO",
        )

        print()
        print("Final safety step: requesting PD_5V from Charger B...")
        final_result = controller.set_voltage_result(
            5,
            timeout=args.request_timeout,
        )
        verify_pdo_result(
            final_result,
            expected_voltage=5,
            tolerance=args.tolerance,
        )
        final_5v_confirmed = True

        print(f"Final result: {final_result.raw_text}")
        print(f"Final measured voltage: {final_result.measured_voltage:.3f}V")
        verify_lua_alive(
            controller,
            timeout=5.0,
            stage="final Charger B PD_5V",
        )

        print()
        print("=" * 72)
        print("PASS: Phase 5 Charger A to Charger B swap completed")
        print(f"Charger A result: {charger_a_result.raw_text}")
        print(f"Charger B rejection: {rejection.raw_text}")
        print(f"Charger B supported result: {charger_b_result.raw_text}")
        print("Charger A PDO capability was not reused for Charger B")
        print("Lua remained active without rerunning onBoot.lua")
        print("Raspberry Pi and KT002 PC USB remained connected")
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
        if controller.connected and charger_b_connected and not final_5v_confirmed:
            attempt_safe_5v(
                controller,
                timeout=args.request_timeout,
                tolerance=args.tolerance,
            )

        controller.close()
        print("KT002 USB connection closed")


if __name__ == "__main__":
    raise SystemExit(main())
