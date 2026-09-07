#!/usr/bin/env python3
"""Safe smoke test for drivers.kt002.KT002Controller.

No PD charger or load is required. The KT002 must be running the verified
onBoot.lua receiver. This test performs protocol PING and Lua PING only.
"""

from drivers.kt002 import KT002Controller, KT002Error


def main() -> int:
    try:
        with KT002Controller(timeout=3.0) as kt002:
            print(f"Connected: VID=0483 PID={kt002.pid:04X}")

            protocol_reply = kt002.ping()
            print(f"Protocol PING: 0x{protocol_reply.header:08X}")

            lua_reply = kt002.lua_ping()
            print(f"Lua_MOSI ACK: 0x{lua_reply.header:08X}")
            print("Check KT002 display: Raspberry Pi connected")

        print("PASS")
        return 0

    except KT002Error as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
