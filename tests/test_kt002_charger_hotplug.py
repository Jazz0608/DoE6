#!/usr/bin/env python3
"""KT002 Phase 5 PD charger hot-plug hardware regression.

Test sequence:
    1. Connect KT002 to Raspberry Pi and confirm Protocol/Lua health.
    2. Establish a supported baseline PDO, default 9V.
    3. Prompt the operator to unplug only the PD charger from KT002.
    4. Request the baseline PDO again and require a typed failure.
    5. Verify Lua still returns PONG:KT002 after charger removal.
    6. Prompt the operator to reconnect the same charger.
    7. Retry the baseline PDO until recovery or the recovery deadline.
    8. Return to the verified safe 5V PDO and close USB resources.

Safety requirements:
    - Verified onBoot.lua is running on KT002.
    - KT002 PC port remains connected to Raspberry Pi for the entire test.
    - Electronic load is disconnected or Input OFF.
    - KT Toolbox is not connected.
    - Only the PD charger cable is unplugged and reconnected when prompted.

This test is interactive by design. It does not automatically continue across
physical hot-plug steps until the operator enters the required confirmation.
"""

from __future__ import annotations

import argparse
import time

from drivers.kt002 import (
    KT002CommandResult,
    KT002Controller,
    KT002Error,
    KT002LuaError,
    KT002PDONotFoundError,
    KT002PDORequestError,
    KT002PDOResult,
    KT002PDSourceError,
    KT002TimeoutError,
    KT002VoltageVerificationError,
)


DEFAULT_BASELINE_VOLTAGE = 9


def require_operator_token(prompt: str, expected: str) -> None:
    """Require an explicit operator token before a physical test step."""

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
    """Require the KT002 Lua event loop to answer PONG:KT002."""

    result = controller.lua_ping_result(timeout=timeout)

    if not isinstance(result, KT002CommandResult):
        raise TypeError(
            "lua_ping_result() did not return KT002CommandResult"
        )
    if not result.success:
        raise RuntimeError(
            f"Lua PING reported success=False during {stage}"
        )
    if result.raw_text != "PONG:KT002":
        raise RuntimeError(
            f"Unexpected Lua PING during {stage}: {result.raw_text!r}"
        )

    print(f"Lua health during {stage}: {result.raw_text}")
    print(f"PASS: Lua event loop active during {stage}")
    return result


def verify_supported_pdo(
    result: KT002PDOResult,
    *,
    expected_voltage: int,
    tolerance: float,
) -> None:
    """Verify a structured successful PDO result."""

    if not isinstance(result, KT002PDOResult):
        raise TypeError("Expected KT002PDOResult")
    if not result.success:
        raise RuntimeError("Supported PDO returned success=False")
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
    """Request and verify one known supported Fixed PDO."""

    print()
    print(f"{label}: requesting PD_{voltage}V...")
    result = controller.set_voltage_result(voltage, timeout=timeout)
    verify_supported_pdo(
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


def verify_failure_metadata(
    error: KT002LuaError,
    *,
    command: str,
    voltage: int,
) -> None:
    """Verify metadata preserved by a typed hot-unplug failure."""

    if error.command != command:
        raise RuntimeError(
            "Exception command mismatch: "
            f"expected {command!r}, received {error.command!r}"
        ) from error
    if not isinstance(error.raw_text, str) or not error.raw_text:
        raise RuntimeError(
            "Exception did not preserve a non-empty raw_text"
        ) from error
    if not error.raw_text.startswith("ERROR:"):
        raise RuntimeError(
            f"Unexpected Lua error text: {error.raw_text!r}"
        ) from error

    if isinstance(error, (KT002PDONotFoundError, KT002PDORequestError)):
        if error.requested_voltage != voltage:
            raise RuntimeError(
                "Exception requested_voltage mismatch: "
                f"expected {voltage}, received {error.requested_voltage}"
            ) from error


def request_after_unplug(
    controller: KT002Controller,
    voltage: int,
    *,
    timeout: float,
) -> KT002LuaError:
    """Require a PDO request after charger removal to fail with typed error."""

    command = f"PD_{voltage}V"
    print()
    print(f"Requesting {command} after PD charger removal...")
    started = time.monotonic()

    try:
        unexpected = controller.set_voltage_result(voltage, timeout=timeout)
    except (KT002PDSourceError, KT002PDONotFoundError, KT002PDORequestError) as error:
        elapsed = time.monotonic() - started
        verify_failure_metadata(
            error,
            command=command,
            voltage=voltage,
        )

        print(f"Exception type: {type(error).__name__}")
        if hasattr(error, "requested_voltage"):
            print(
                "requested_voltage: "
                f"{getattr(error, 'requested_voltage')}"
            )
        if hasattr(error, "pdo_index"):
            print(f"pdo_index: {getattr(error, 'pdo_index')}")
        print(f"command: {error.command}")
        print(f"raw_text: {error.raw_text}")
        print(f"Failure latency: {elapsed:.3f}s")
        print("PASS: unplugged-charger PDO request returned typed failure")
        return error
    except KT002TimeoutError as error:
        elapsed = time.monotonic() - started
        raise RuntimeError(
            "Hot-unplug PDO request timed out instead of returning a typed "
            f"Lua error after {elapsed:.3f}s"
        ) from error
    except KT002LuaError as error:
        elapsed = time.monotonic() - started
        verify_failure_metadata(
            error,
            command=command,
            voltage=voltage,
        )
        raise RuntimeError(
            "Hot-unplug returned an unclassified Lua error: "
            f"{type(error).__name__}, raw_text={error.raw_text!r}, "
            f"latency={elapsed:.3f}s"
        ) from error

    if isinstance(unexpected, KT002PDOResult):
        raise RuntimeError(
            "PDO request after charger removal incorrectly returned success: "
            f"{unexpected!r}"
        )
    raise RuntimeError(
        "PDO request after charger removal returned an unexpected object: "
        f"{unexpected!r}"
    )


def recover_supported_pdo(
    controller: KT002Controller,
    voltage: int,
    *,
    request_timeout: float,
    recovery_timeout: float,
    retry_interval: float,
    tolerance: float,
) -> KT002PDOResult:
    """Retry a supported PDO after charger reconnection until recovered."""

    deadline = time.monotonic() + recovery_timeout
    attempt = 0
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        attempt += 1
        print()
        print(f"Recovery attempt {attempt}: requesting PD_{voltage}V...")

        try:
            result = controller.set_voltage_result(
                voltage,
                timeout=request_timeout,
            )
            verify_supported_pdo(
                result,
                expected_voltage=voltage,
                tolerance=tolerance,
            )
            print(f"Raw result: {result.raw_text}")
            print(f"Measured: {result.measured_voltage:.3f}V")
            print(f"PDO index: {result.pdo_index}")
            print(
                f"PASS: PD_{voltage}V recovered after charger reconnection"
            )
            return result
        except (
            KT002PDSourceError,
            KT002PDONotFoundError,
            KT002PDORequestError,
            KT002TimeoutError,
        ) as error:
            last_error = error
            remaining = max(0.0, deadline - time.monotonic())
            print(
                f"Recovery attempt {attempt} not ready: "
                f"{type(error).__name__}: {error}"
            )
            print(f"Recovery time remaining: {remaining:.1f}s")
            if remaining <= 0:
                break
            time.sleep(min(retry_interval, remaining))

    raise RuntimeError(
        f"PD_{voltage}V did not recover within "
        f"{recovery_timeout:.1f}s; last error: {last_error!r}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="KT002 Phase 5 PD charger hot-plug hardware regression"
    )
    parser.add_argument(
        "--baseline",
        type=int,
        default=DEFAULT_BASELINE_VOLTAGE,
        choices=(5, 9, 12, 15, 20),
        help="known supported PDO used before and after hot-plug, default: 9V",
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
        help="overall reconnection recovery window, default: 45 seconds",
    )
    parser.add_argument(
        "--retry-interval",
        type=float,
        default=2.0,
        help="delay between recovery attempts, default: 2 seconds",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1.0,
        help="allowed absolute voltage deviation, default: 1.0V",
    )
    args = parser.parse_args()

    if args.request_timeout <= 0:
        parser.error("--request-timeout must be greater than zero")
    if args.recovery_timeout <= 0:
        parser.error("--recovery-timeout must be greater than zero")
    if args.retry_interval <= 0:
        parser.error("--retry-interval must be greater than zero")
    if args.tolerance <= 0:
        parser.error("--tolerance must be greater than zero")

    print("=" * 72)
    print("KT002 Phase 5 PD charger hot-plug regression")
    print(f"Baseline and recovery PDO: {args.baseline}V")
    print("Keep the KT002 PC USB connection attached for the entire test.")
    print("Electronic load must be disconnected or Input OFF.")
    print("=" * 72)

    controller = KT002Controller(timeout=3.0)
    charger_reconnected = False
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
            stage="initial connected-charger check",
        )

        request_supported_pdo(
            controller,
            args.baseline,
            timeout=args.request_timeout,
            tolerance=args.tolerance,
            label="Baseline",
        )

        print()
        print("HOT-UNPLUG STEP")
        print("Unplug only the PD charger cable from the KT002 Type-C port.")
        print("Do not unplug the KT002 PC USB cable from Raspberry Pi.")
        require_operator_token(
            "After the PD charger is fully unplugged, type UNPLUGGED: ",
            "UNPLUGGED",
        )

        unplug_error = request_after_unplug(
            controller,
            args.baseline,
            timeout=args.request_timeout,
        )
        verify_lua_alive(
            controller,
            timeout=5.0,
            stage="charger removal",
        )

        print()
        print("HOT-RECONNECT STEP")
        print("Reconnect the same PD charger to the KT002 Type-C port.")
        require_operator_token(
            "After the charger is fully reconnected, type RECONNECTED: ",
            "RECONNECTED",
        )
        charger_reconnected = True

        recovered_result = recover_supported_pdo(
            controller,
            args.baseline,
            request_timeout=args.request_timeout,
            recovery_timeout=args.recovery_timeout,
            retry_interval=args.retry_interval,
            tolerance=args.tolerance,
        )
        verify_lua_alive(
            controller,
            timeout=5.0,
            stage="charger reconnection",
        )

        print()
        print("Final safety step: requesting PD_5V...")
        final_result = controller.set_voltage_result(
            5,
            timeout=args.request_timeout,
        )
        verify_supported_pdo(
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
            stage="final PD_5V",
        )

        print()
        print("=" * 72)
        print("PASS: Phase 5 PD charger hot-plug regression completed")
        print(f"Removal exception: {type(unplug_error).__name__}")
        print(f"Recovered result: {recovered_result.raw_text}")
        print("Lua event loop remained active")
        print("Same charger recovered without restarting Raspberry Pi")
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
        if controller.connected and charger_reconnected and not final_5v_confirmed:
            print()
            print("Safety recovery: attempting PD_5V...")
            try:
                result = controller.set_voltage_result(
                    5,
                    timeout=args.request_timeout,
                )
                verify_supported_pdo(
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
