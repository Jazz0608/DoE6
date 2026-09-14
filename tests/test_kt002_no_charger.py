#!/usr/bin/env python3
"""KT002 Phase 5 no-PD-charger hardware regression.

Test condition:
    - KT002 PC port is connected to Raspberry Pi.
    - Verified onBoot.lua is running.
    - No PD charger is connected to the KT002 Type-C input.
    - Electronic load is disconnected or Input OFF.
    - KT Toolbox is not connected.

The test verifies:
    1. KT002 USB and Shizuku Protocol PING remain operational.
    2. Lua MISO PING returns PONG:KT002 without a charger.
    3. A 9V PDO request does not return KT002PDOResult success.
    4. A typed PD-source or PDO-not-found exception is returned promptly.
    5. Exception command and raw_text metadata are preserved.
    6. Lua remains responsive after the failed PDO request.
    7. USB resources are released normally.

No PD voltage can be restored while no charger is connected. The script does
not treat that condition as a safety-recovery failure because VBUS is absent.
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
    KT002PDOResult,
    KT002PDSourceError,
    KT002TimeoutError,
)


DEFAULT_TEST_VOLTAGE = 9


def verify_lua_ping(
    controller: KT002Controller,
    *,
    timeout: float,
    stage: str,
) -> KT002CommandResult:
    """Require the Lua controller to answer PONG:KT002."""

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
            f"Unexpected Lua PING result during {stage}: "
            f"{result.raw_text!r}"
        )

    print(f"Lua health during {stage}: {result.raw_text}")
    print(f"PASS: Lua event loop active during {stage}")
    return result


def verify_error_metadata(
    error: KT002LuaError,
    *,
    command: str,
) -> None:
    """Verify metadata preserved by a typed Lua error."""

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


def request_without_charger(
    controller: KT002Controller,
    voltage: int,
    *,
    timeout: float,
) -> KT002LuaError:
    """Require a PDO request without a charger to fail with a typed error."""

    command = f"PD_{voltage}V"
    print()
    print(f"Requesting {command} with no PD charger connected...")
    started = time.monotonic()

    try:
        unexpected = controller.set_voltage_result(
            voltage,
            timeout=timeout,
        )
    except KT002PDSourceError as error:
        elapsed = time.monotonic() - started
        verify_error_metadata(error, command=command)
        print(f"Exception type: {type(error).__name__}")
        print(f"command: {error.command}")
        print(f"raw_text: {error.raw_text}")
        print(f"Failure latency: {elapsed:.3f}s")
        print("PASS: no-charger request produced KT002PDSourceError")
        return error
    except KT002PDONotFoundError as error:
        elapsed = time.monotonic() - started
        verify_error_metadata(error, command=command)

        if error.requested_voltage != voltage:
            raise RuntimeError(
                "KT002PDONotFoundError requested_voltage mismatch: "
                f"expected {voltage}, "
                f"received {error.requested_voltage}"
            ) from error

        print(f"Exception type: {type(error).__name__}")
        print(f"requested_voltage: {error.requested_voltage}")
        print(f"command: {error.command}")
        print(f"raw_text: {error.raw_text}")
        print(f"Failure latency: {elapsed:.3f}s")
        print(
            "PASS: no-charger request produced typed "
            "KT002PDONotFoundError"
        )
        print(
            "NOTE: current Lua classified the absent source as "
            "PDO not found rather than PD source unavailable"
        )
        return error
    except KT002TimeoutError as error:
        elapsed = time.monotonic() - started
        raise RuntimeError(
            "No-charger PDO request timed out instead of returning "
            f"a typed Lua error after {elapsed:.3f}s"
        ) from error
    except KT002LuaError as error:
        elapsed = time.monotonic() - started
        verify_error_metadata(error, command=command)
        raise RuntimeError(
            "No-charger PDO request returned an unclassified Lua error: "
            f"{type(error).__name__}, raw_text={error.raw_text!r}, "
            f"latency={elapsed:.3f}s"
        ) from error

    if isinstance(unexpected, KT002PDOResult):
        raise RuntimeError(
            "No-charger PDO request incorrectly returned success: "
            f"{unexpected!r}"
        )

    raise RuntimeError(
        "No-charger PDO request returned an unexpected object: "
        f"{unexpected!r}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="KT002 Phase 5 no-PD-charger hardware regression"
    )
    parser.add_argument(
        "--voltage",
        type=int,
        default=DEFAULT_TEST_VOLTAGE,
        choices=(9, 12, 15, 20),
        help="PDO voltage to request with no charger, default: 9V",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="maximum Lua result wait time, default: 8.0 seconds",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=1.0,
        help="pause before the post-failure Lua health check, default: 1.0",
    )
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.pause < 0:
        parser.error("--pause must not be negative")

    print("=" * 72)
    print("KT002 Phase 5 no-PD-charger regression")
    print("Required condition: no PD charger connected to KT002")
    print(f"PDO request under test: PD_{args.voltage}V")
    print("Electronic load must be disconnected or Input OFF.")
    print("=" * 72)

    controller = KT002Controller(timeout=3.0)

    try:
        controller.connect()
        print(
            f"Connected: VID={controller.VID:04X} "
            f"PID={controller.pid:04X}"
        )
        print(f"Controller: {KT002Controller.__module__}")

        protocol_reply = controller.ping()
        print(f"Protocol PING: 0x{protocol_reply.header:08X}")

        verify_lua_ping(
            controller,
            timeout=5.0,
            stage="initial no-charger check",
        )

        error = request_without_charger(
            controller,
            args.voltage,
            timeout=args.timeout,
        )

        if args.pause:
            time.sleep(args.pause)

        verify_lua_ping(
            controller,
            timeout=5.0,
            stage=f"failed PD_{args.voltage}V request",
        )

        print()
        print("=" * 72)
        print("PASS: Phase 5 no-PD-charger regression completed")
        print(f"Observed exception: {type(error).__name__}")
        print("PDO request was not misreported as success")
        print("Lua event loop remained active")
        print("No charger was connected, so no VBUS recovery was required")
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
        controller.close()
        print("KT002 USB connection closed")


if __name__ == "__main__":
    raise SystemExit(main())
