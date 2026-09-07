#!/usr/bin/env python3
"""Full Fixed PDO regression test for the modular KT002 driver.

Verified command sequence supported by the current onBoot.lua:
    PING -> PD_5V -> PD_9V -> PD_12V -> PD_15V -> PD_20V -> PD_5V

This test deliberately does not send INIT, CAPS, STATUS, CLEAR, or RELEASE,
because those commands are not supported by the current verified Lua script.

Safety requirements:
    - KT002 PC port connected directly to Raspberry Pi
    - Supported PD charger connected and powered
    - KT002 PD COM enabled
    - Electronic load disconnected or Input OFF
    - Windows KT Toolbox not connected
"""

from __future__ import annotations

import argparse
import time

from drivers.kt002 import KT002Controller, KT002Error


PDO_SEQUENCE = (5, 9, 12, 15, 20)


def confirm_voltage(target_voltage: int) -> bool:
    """Require the operator to confirm the observed KT002 voltage."""
    answer = input(
        f"Confirm KT002 is approximately {target_voltage}V. "
        f"Type {target_voltage} to continue: "
    ).strip()
    return answer == str(target_voltage)


def request_and_confirm(
    kt002: KT002Controller,
    voltage: int,
    settle_seconds: float,
) -> None:
    """Send one Fixed PDO command and require visual confirmation."""
    print()
    print(f"Requesting PD_{voltage}V...")
    reply = kt002.set_voltage(voltage)
    print(f"Lua_MOSI ACK: 0x{reply.header:08X}")
    print(f"Waiting {settle_seconds:.1f} seconds for stabilization...")
    time.sleep(settle_seconds)

    if not confirm_voltage(voltage):
        raise RuntimeError(
            f"Operator did not confirm approximately {voltage}V"
        )

    print(f"PASS: PD_{voltage}V confirmed")


def return_to_safe_5v(
    kt002: KT002Controller,
    settle_seconds: float,
) -> bool:
    """Return to 5V using the verified PD_5V command."""
    print()
    print("Safety action: requesting verified PD_5V command...")

    try:
        reply = kt002.set_voltage(5)
        print(f"PD_5V Lua_MOSI ACK: 0x{reply.header:08X}")
        time.sleep(settle_seconds)
        print("CHECK: KT002 must be approximately 5V.")
        return True
    except KT002Error as error:
        print(f"ERROR: unable to request safe 5V: {error}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "KT002 modular-driver full Fixed PDO regression: "
            "5V, 9V, 12V, 15V, 20V, then 5V"
        )
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=3.0,
        help="Seconds to wait after each PDO request, default: 3.0",
    )
    args = parser.parse_args()

    if args.settle <= 0:
        parser.error("--settle must be greater than zero")

    print("=" * 72)
    print("KT002 modular driver full Fixed PDO regression")
    print("Sequence: 5V -> 9V -> 12V -> 15V -> 20V -> 5V")
    print("Electronic load must be disconnected or Input OFF.")
    print("=" * 72)

    kt002 = KT002Controller(timeout=3.0)
    final_5v_requested = False

    try:
        kt002.connect()
        print(f"Connected: VID={kt002.VID:04X} PID={kt002.pid:04X}")
        print(f"Controller module: {KT002Controller.__module__}")

        if KT002Controller.__module__ != "drivers.kt002.controller":
            raise RuntimeError(
                "Modular controller is not active: "
                f"{KT002Controller.__module__}"
            )

        protocol_reply = kt002.ping()
        print(f"Protocol PING: 0x{protocol_reply.header:08X}")

        lua_reply = kt002.lua_ping()
        print(f"Lua_MOSI PING ACK: 0x{lua_reply.header:08X}")
        print("CHECK: KT002 should display Raspberry Pi connected.")

        for voltage in PDO_SEQUENCE:
            request_and_confirm(kt002, voltage, args.settle)

        print()
        print("Final safety step: return to 5V")
        reply = kt002.set_voltage(5)
        final_5v_requested = True
        print(f"Final PD_5V Lua_MOSI ACK: 0x{reply.header:08X}")
        time.sleep(args.settle)

        if not confirm_voltage(5):
            raise RuntimeError("Final 5V state was not confirmed")

        print()
        print("=" * 72)
        print("PASS: full Fixed PDO regression completed")
        print("Observed sequence: 5V -> 9V -> 12V -> 15V -> 20V -> 5V")
        print("=" * 72)
        return 0

    except KeyboardInterrupt:
        print()
        print("ABORT: test interrupted by operator")
        return 130

    except (KT002Error, RuntimeError) as error:
        print()
        print(f"FAIL: {error}")
        return 1

    finally:
        if kt002.connected and not final_5v_requested:
            return_to_safe_5v(kt002, args.settle)

        kt002.close()
        print("KT002 USB connection closed.")


if __name__ == "__main__":
    raise SystemExit(main())
