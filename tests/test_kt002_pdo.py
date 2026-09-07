#!/usr/bin/env python3
"""
KT002 Fixed PDO control test.

Test sequence:
    1. Connect to KT002
    2. Verify Shizuku protocol PING
    3. Verify onBoot.lua communication
    4. Request 5V
    5. Request 9V
    6. RELEASE back to 5V

Required connections:
    PD Charger -> USB-C cable -> KT002
    KT002 PC port -> USB cable -> Raspberry Pi

Requirements:
    - KT002 PD COM switch is ON
    - Formal onBoot.lua is running
    - Do not connect the DC Load during this initial test
    - Windows and KT Toolbox are not required
"""

import time

from drivers.kt002 import (
    KT002Controller,
    KT002Error,
)


SETTLE_TIME_SECONDS = 3.0


def wait_for_voltage_change(target_voltage: int) -> None:
    """Wait for PD negotiation and prompt the operator to check KT002 VBUS."""

    print()
    print(f"等待 KT002 切換至 {target_voltage}V...")
    time.sleep(SETTLE_TIME_SECONDS)

    print(
        f"請確認 KT002 畫面顯示接近 {target_voltage}V，"
        "且畫面沒有顯示 ERROR。"
    )


def main() -> int:
    print("=" * 60)
    print("KT002 PDO control test")
    print("Test sequence: 5V -> 9V -> 5V")
    print("=" * 60)

    kt002 = KT002Controller(timeout=3.0)

    try:
        # --------------------------------------------------------
        # 1. Connect to KT002
        # --------------------------------------------------------
        kt002.connect()

        print(
            f"KT002 connected: VID=0483 PID={kt002.pid:04X}"
        )

        # --------------------------------------------------------
        # 2. Verify direct Shizuku protocol communication
        # --------------------------------------------------------
        protocol_reply = kt002.ping()

        print(
            "Protocol PING reply: "
            f"0x{protocol_reply.header:08X}"
        )

        # --------------------------------------------------------
        # 3. Verify command delivery to onBoot.lua
        # --------------------------------------------------------
        lua_reply = kt002.lua_ping()

        print(
            "Lua_MOSI ACK: "
            f"0x{lua_reply.header:08X}"
        )

        print(
            "確認 KT002 畫面顯示：Raspberry Pi connected"
        )

        # --------------------------------------------------------
        # 4. Request 5V PDO
        # --------------------------------------------------------
        print()
        print("[STEP 1] Request PD 5V")

        reply = kt002.set_voltage(5)

        print(
            "PD_5V Lua_MOSI ACK: "
            f"0x{reply.header:08X}"
        )

        wait_for_voltage_change(5)

        # --------------------------------------------------------
        # 5. Request 9V PDO
        # --------------------------------------------------------
        print()
        print("[STEP 2] Request PD 9V")

        reply = kt002.set_voltage(9)

        print(
            "PD_9V Lua_MOSI ACK: "
            f"0x{reply.header:08X}"
        )

        wait_for_voltage_change(9)

        # --------------------------------------------------------
        # 6. Return to 5V
        # --------------------------------------------------------
        print()
        print("[STEP 3] RELEASE to PD 5V")

        reply = kt002.release()

        print(
            "RELEASE Lua_MOSI ACK: "
            f"0x{reply.header:08X}"
        )

        wait_for_voltage_change(5)

        print()
        print("=" * 60)
        print("PDO command sequence completed")
        print("Final expected output: approximately 5V")
        print("=" * 60)

        return 0

    except KT002Error as error:
        print()
        print(f"KT002 TEST FAILED: {error}")

        # 若 PD 指令執行途中發生錯誤，嘗試回到 5V
        if kt002.connected:
            try:
                print("Attempting emergency RELEASE to 5V...")
                kt002.release()
                time.sleep(SETTLE_TIME_SECONDS)
                print("Emergency RELEASE command sent.")
            except KT002Error as release_error:
                print(
                    "Emergency RELEASE failed: "
                    f"{release_error}"
                )

        return 1

    except KeyboardInterrupt:
        print()
        print("Test interrupted by operator.")

        # Ctrl+C 時也嘗試回到 5V
        if kt002.connected:
            try:
                print("Attempting RELEASE to 5V...")
                kt002.release()
                time.sleep(SETTLE_TIME_SECONDS)
            except KT002Error as release_error:
                print(
                    "RELEASE failed: "
                    f"{release_error}"
                )

        return 130

    finally:
        kt002.close()
        print("KT002 USB connection closed.")


if __name__ == "__main__":
    raise SystemExit(main())