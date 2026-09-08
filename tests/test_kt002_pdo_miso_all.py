#!/usr/bin/env python3
"""KT002 full Fixed PDO Lua MISO regression test.

Test sequence:
    Protocol PING
    Lua PING with MISO result
    5V -> 9V -> 12V -> 15V -> 20V -> 5V

Each PDO request must receive both:
    1. Lua_MOSI protocol ACK 0x80000000
    2. Lua MISO final result containing OK:PD_<voltage>V:

Safety requirements:
    - PD charger connected to KT002 and powered
    - Electronic load disconnected or Input OFF
    - Verified onBoot.lua running
    - KT Toolbox not connected
"""

from __future__ import annotations

import argparse
import re
import time

from drivers.kt002 import KT002Controller, KT002Error


PDO_SEQUENCE = (5, 9, 12, 15, 20)
PDO_RESULT_PATTERN = re.compile(
    r"^OK:PD_(?P<requested>5|9|12|15|20)V:"
    r"(?P<measured>[0-9]+(?:\.[0-9]+)?)V:PDO=(?P<pdo>[0-9]+)$"
)


def parse_pdo_result(result: str) -> tuple[int, float, int]:
    """Parse one verified Lua PDO result line."""
    match = PDO_RESULT_PATTERN.fullmatch(result.strip())
    if match is None:
        raise RuntimeError(f"Unexpected PDO result format: {result!r}")

    return (
        int(match.group("requested")),
        float(match.group("measured")),
        int(match.group("pdo")),
    )


def request_and_verify(
    controller: KT002Controller,
    voltage: int,
    *,
    timeout: float,
    tolerance: float,
) -> str:
    """Request one Fixed PDO and verify its Lua MISO result."""
    print()
    print(f"Requesting PD_{voltage}V...")

    result = controller.set_voltage_wait_result(
        voltage,
        timeout=timeout,
    )
    requested, measured, pdo_index = parse_pdo_result(result)

    if requested != voltage:
        raise RuntimeError(
            f"Requested {voltage}V but Lua reported {requested}V"
        )

    deviation = abs(measured - voltage)
    if deviation > tolerance:
        raise RuntimeError(
            f"PD_{voltage}V measured {measured:.3f}V, "
            f"outside tolerance +/-{tolerance:.3f}V"
        )

    print(f"Lua MISO: {result}")
    print(
        f"PASS: PD_{voltage}V, measured={measured:.3f}V, "
        f"PDO={pdo_index}, deviation={deviation:.3f}V"
    )
    return result


def return_to_5v(
    controller: KT002Controller,
    *,
    timeout: float,
    tolerance: float,
) -> bool:
    """Attempt to return KT002 to the verified 5V Fixed PDO."""
    if not controller.connected:
        return False

    print()
    print("Safety action: returning to PD_5V...")
    try:
        request_and_verify(
            controller,
            5,
            timeout=timeout,
            tolerance=tolerance,
        )
        return True
    except Exception as error:
        print(f"WARNING: unable to confirm final 5V: {error}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="KT002 full Fixed PDO Lua MISO regression test"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="MISO result timeout per PDO in seconds, default: 8.0",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1.0,
        help="allowed voltage deviation in volts, default: 1.0",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=1.0,
        help="pause between PDO requests in seconds, default: 1.0",
    )
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.tolerance <= 0:
        parser.error("--tolerance must be greater than zero")
    if args.pause < 0:
        parser.error("--pause must not be negative")

    print("=" * 72)
    print("KT002 full Fixed PDO Lua MISO regression")
    print("Sequence: 5V -> 9V -> 12V -> 15V -> 20V -> 5V")
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

        lua_result = controller.lua_ping_wait_result(timeout=5.0)
        print(f"Lua MISO PING: {lua_result}")
        if "PONG:KT002" not in lua_result:
            raise RuntimeError(
                f"Unexpected Lua PING result: {lua_result!r}"
            )

        print("PASS: Protocol PING and Lua MISO PING")

        for voltage in PDO_SEQUENCE:
            request_and_verify(
                controller,
                voltage,
                timeout=args.timeout,
                tolerance=args.tolerance,
            )
            if args.pause:
                time.sleep(args.pause)

        print()
        print("Final safety step: PD_5V")
        request_and_verify(
            controller,
            5,
            timeout=args.timeout,
            tolerance=args.tolerance,
        )
        final_5v_confirmed = True

        print()
        print("=" * 72)
        print("PASS: full Fixed PDO Lua MISO regression completed")
        print("Verified: 5V -> 9V -> 12V -> 15V -> 20V -> 5V")
        print("=" * 72)
        return 0

    except KeyboardInterrupt:
        print()
        print("ABORT: test interrupted by operator")
        return 130

    except (KT002Error, RuntimeError, ValueError) as error:
        print()
        print(f"FAIL: {error}")
        return 1

    finally:
        if controller.connected and not final_5v_confirmed:
            return_to_5v(
                controller,
                timeout=args.timeout,
                tolerance=args.tolerance,
            )

        controller.close()
        print("KT002 USB connection closed")


if __name__ == "__main__":
    raise SystemExit(main())
