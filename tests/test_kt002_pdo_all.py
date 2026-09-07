#!/usr/bin/env python3
"""
KT002 全 PDO 指令測試

測試順序：
    PING
    INIT
    CAPS
    PD_5V
    PD_9V
    PD_12V
    PD_15V
    PD_20V
    RELEASE

通訊架構：
    Raspberry Pi Python
        -> USB
        -> Shizuku Protocol
        -> Lua_MOSI
        -> KT002 onBoot.lua

注意：
1. 不需要 Windows 或 KT Toolbox。
2. KT002 必須正在執行正式版 onBoot.lua。
3. 測試時電子負載必須先保持關閉。
4. 不支援的 PDO 應由 onBoot.lua 回覆錯誤，不應強制切換。
5. 程式結束或發生錯誤時，會嘗試傳送 RELEASE 回到 5V。
6. 目前程式確認的是協定 ACK，尚未讀取 Lua 的文字回覆。
"""

from __future__ import annotations

import argparse
import struct
import sys
import time

import usb.core
import usb.util


VID = 0x0483
VALID_PIDS = (
    0xFFFF,
    0xFFFE,
    0x374B,
)

INTERFACE = 0
EP_OUT = 0x01
EP_IN = 0x81

REQUEST_MARKER = 0x01
LUA_MOSI_REQUEST_TYPE = 0x1F

USB_WRITE_TIMEOUT_MS = 2000
USB_READ_TIMEOUT_MS = 3000
MAX_FRAME_PAYLOAD = 4096

DEFAULT_SETTLE_TIME = 3.0

PDO_COMMANDS = (
    ("PD_5V", 5),
    ("PD_9V", 9),
    ("PD_12V", 12),
    ("PD_15V", 15),
    ("PD_20V", 20),
)


def xor8(data: bytes) -> int:
    """計算 Shizuku Payload XOR。"""

    result = 0

    for byte in data:
        result ^= byte

    return result


def make_frame(payload: bytes) -> bytes:
    """
    建立 Shizuku Protocol 封包。

    格式：
        A5
        Payload Length, UInt32 Little-Endian
        Payload
        Payload XOR
        5A
    """

    return (
        b"\xA5"
        + struct.pack("<I", len(payload))
        + payload
        + bytes(
            (
                xor8(payload),
                0x5A,
            )
        )
    )


def make_lua_mosi_packet(
    command: str,
    caller_id: int = 0,
) -> bytes:
    """
    建立 Lua_MOSI Request。

    ShizukuProtocol.dll 的 Lua_MOSI 格式：

        Request Type = 0x1F

        Argument[0] =
            content_length << 16

        command bytes 從 Argument Buffer
        的 Byte Offset 4 開始。
    """

    content = command.encode("utf-8")

    if not content:
        raise ValueError(
            "Command must not be empty"
        )

    if len(content) > 0xFFFF:
        raise ValueError(
            "Command exceeds Lua_MOSI limit"
        )

    uint32_count = (
        (len(content) + 3) // 4
    ) + 4

    arguments = bytearray(
        uint32_count * 4
    )

    struct.pack_into(
        "<I",
        arguments,
        0,
        len(content) << 16,
    )

    arguments[
        4:4 + len(content)
    ] = content

    request_header = (
        (caller_id << 16)
        | (
            LUA_MOSI_REQUEST_TYPE
            << 8
        )
        | REQUEST_MARKER
    )

    payload = (
        struct.pack(
            "<I",
            request_header,
        )
        + bytes(arguments)
    )

    return make_frame(payload)


def find_kt002():
    """依官方 VID/PID 清單尋找 KT002。"""

    for pid in VALID_PIDS:
        device = usb.core.find(
            idVendor=VID,
            idProduct=pid,
        )

        if device is not None:
            return device, pid

    return None, None


def drain_input(device) -> None:
    """清除之前留在 IN Endpoint 的封包。"""

    while True:
        try:
            device.read(
                EP_IN,
                4096,
                timeout=50,
            )

        except usb.core.USBTimeoutError:
            return


def extract_frames(
    buffer: bytearray,
):
    """從 USB Receive Buffer 取出完整 Shizuku Frame。"""

    frames = []

    while True:
        try:
            start = buffer.index(0xA5)

        except ValueError:
            buffer.clear()
            break

        if start > 0:
            del buffer[:start]

        if len(buffer) < 7:
            break

        payload_length = (
            struct.unpack_from(
                "<I",
                buffer,
                1,
            )[0]
        )

        if payload_length > MAX_FRAME_PAYLOAD:
            del buffer[0]
            continue

        total_length = (
            payload_length + 7
        )

        if len(buffer) < total_length:
            break

        raw_frame = bytes(
            buffer[:total_length]
        )

        del buffer[:total_length]

        payload = raw_frame[
            5:5 + payload_length
        ]

        checksum = raw_frame[
            5 + payload_length
        ]

        terminator = raw_frame[
            6 + payload_length
        ]

        valid = (
            checksum == xor8(payload)
            and terminator == 0x5A
        )

        frames.append(
            (
                raw_frame,
                payload,
                valid,
            )
        )

    return frames


def decode_header(
    payload: bytes,
) -> None:
    """顯示 Shizuku 回覆 Header。"""

    if len(payload) < 4:
        print(
            "RX payload shorter than 4 bytes"
        )

        return

    header = struct.unpack_from(
        "<I",
        payload,
        0,
    )[0]

    caller_id = (
        header >> 16
    ) & 0xFFFF

    message_type = (
        header >> 8
    ) & 0xFF

    low_byte = (
        header & 0xFF
    )

    print(
        f"RX header: 0x{header:08X}"
    )

    print(
        f"Caller ID: {caller_id}"
    )

    print(
        f"Message Type: "
        f"0x{message_type:02X}"
    )

    print(
        f"Low Byte: 0x{low_byte:02X}"
    )


class KT002MOSI:
    """KT002 Lua_MOSI 最小測試控制器。"""

    def __init__(
        self,
        caller_id: int = 0,
    ):
        self.caller_id = caller_id
        self.device = None
        self.pid = None

        self.claimed = False
        self.detached = False

    def connect(self) -> None:
        self.device, self.pid = (
            find_kt002()
        )

        if self.device is None:
            raise RuntimeError(
                "KT002 not found. "
                "Expected VID 0483 and "
                "PID FFFF/FFFE/374B."
            )

        print(
            "KT002 found: "
            f"VID=0483 PID={self.pid:04X}"
        )

        try:
            if self.device.is_kernel_driver_active(
                INTERFACE
            ):
                self.device.detach_kernel_driver(
                    INTERFACE
                )

                self.detached = True

                print(
                    "Detached Linux kernel "
                    "driver from interface 0."
                )

        except (
            NotImplementedError,
            usb.core.USBError,
        ):
            pass

        # 不可執行 set_configuration()。
        # KT002 是 Composite USB Device，
        # 重新設定可能造成 Resource busy。
        usb.util.claim_interface(
            self.device,
            INTERFACE,
        )

        self.claimed = True

        for endpoint in (
            EP_OUT,
            EP_IN,
        ):
            try:
                self.device.clear_halt(
                    endpoint
                )

            except usb.core.USBError:
                pass

        drain_input(self.device)

        print(
            "KT002 USB interface ready"
        )

    def send_command(
        self,
        command: str,
        timeout_ms: int = (
            USB_READ_TIMEOUT_MS
        ),
    ) -> bool:
        """
        傳送 Lua_MOSI 命令並等待協定 ACK。

        回傳 True 只代表 KT002 韌體接受
        Lua_MOSI Request，不代表 PDO 已成功切換。
        """

        if self.device is None:
            raise RuntimeError(
                "KT002 is not connected"
            )

        packet = make_lua_mosi_packet(
            command,
            self.caller_id,
        )

        drain_input(self.device)

        print()
        print("=" * 60)
        print(f"Command: {command}")
        print(
            "TX:",
            packet.hex(" ").upper(),
        )

        written = self.device.write(
            EP_OUT,
            packet,
            timeout=USB_WRITE_TIMEOUT_MS,
        )

        print(f"TX bytes: {written}")

        deadline = (
            time.monotonic()
            + timeout_ms / 1000.0
        )

        receive_buffer = bytearray()

        while (
            time.monotonic()
            < deadline
        ):
            remaining_ms = max(
                1,
                int(
                    (
                        deadline
                        - time.monotonic()
                    )
                    * 1000
                ),
            )

            try:
                chunk = bytes(
                    self.device.read(
                        EP_IN,
                        4096,
                        timeout=min(
                            250,
                            remaining_ms,
                        ),
                    )
                )

                receive_buffer.extend(
                    chunk
                )

            except usb.core.USBTimeoutError:
                continue

            frames = extract_frames(
                receive_buffer
            )

            for (
                raw_frame,
                payload,
                valid,
            ) in frames:
                print(
                    "RX:",
                    raw_frame.hex(
                        " "
                    ).upper(),
                )

                print(
                    f"Frame valid: {valid}"
                )

                decode_header(payload)

                if valid:
                    print(
                        "ACK: KT002 accepted "
                        "the Lua_MOSI request"
                    )

                    return True

        print(
            "FAIL: no valid Shizuku ACK"
        )

        return False

    def close(self) -> None:
        if self.device is None:
            return

        if self.claimed:
            try:
                usb.util.release_interface(
                    self.device,
                    INTERFACE,
                )

            except usb.core.USBError:
                pass

        usb.util.dispose_resources(
            self.device
        )

        if self.detached:
            try:
                self.device.attach_kernel_driver(
                    INTERFACE
                )

            except (
                NotImplementedError,
                usb.core.USBError,
            ):
                pass

        self.device = None

        print()
        print("KT002 USB connection closed")


def ask_to_continue(
    command: str,
    voltage: int,
) -> bool:
    """
    高壓 PDO 前要求人工確認。

    目前 Python 尚未解析 Lua MISO 最終結果，
    所以必須查看 KT002 畫面及確認輸出端安全。
    """

    print()
    print(
        f"Next command: {command}"
    )

    print(
        f"Expected voltage: "
        f"approximately {voltage} V"
    )

    print(
        "Make sure the electronic load "
        "is OFF."
    )

    answer = input(
        f"Type {voltage} to continue, "
        "or press Enter to skip: "
    ).strip()

    return answer == str(voltage)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "KT002 direct-USB full PDO "
            "command test"
        )
    )

    parser.add_argument(
        "--settle",
        type=float,
        default=DEFAULT_SETTLE_TIME,
        help=(
            "Seconds to wait after each "
            "PDO command, default: 3"
        ),
    )

    parser.add_argument(
        "--include-high-voltage",
        action="store_true",
        help=(
            "Enable 12V, 15V and 20V "
            "test prompts"
        ),
    )

    args = parser.parse_args()

    kt002 = KT002MOSI()

    release_attempted = False

    try:
        kt002.connect()

        if not kt002.send_command(
            "PING"
        ):
            raise RuntimeError(
                "PING ACK failed"
            )

        print(
            "Check KT002 display for "
            "'Raspberry Pi connected'."
        )

        if not kt002.send_command(
            "INIT",
            timeout_ms=8000,
        ):
            raise RuntimeError(
                "INIT ACK failed"
            )

        time.sleep(1)

        if not kt002.send_command(
            "CAPS",
            timeout_ms=8000,
        ):
            raise RuntimeError(
                "CAPS ACK failed"
            )

        print()
        print(
            "Review the PDO list on "
            "the KT002 display/debug output."
        )

        input(
            "Press Enter to begin the "
            "PDO sequence..."
        )

        for command, voltage in PDO_COMMANDS:
            if (
                voltage >= 12
                and not args.include_high_voltage
            ):
                print(
                    f"SKIP: {command}. "
                    "Use --include-high-voltage "
                    "to enable."
                )

                continue

            if not ask_to_continue(
                command,
                voltage,
            ):
                print(
                    f"SKIP: {command}"
                )

                continue

            acknowledged = (
                kt002.send_command(
                    command,
                    timeout_ms=8000,
                )
            )

            if not acknowledged:
                raise RuntimeError(
                    f"{command} ACK failed"
                )

            print(
                f"Wait {args.settle:.1f} "
                "seconds for voltage "
                "stabilization."
            )

            time.sleep(args.settle)

            print(
                "Check KT002 display and "
                "actual output voltage."
            )

        print()
        print(
            "Returning KT002 to 5 V..."
        )

        release_attempted = True

        if not kt002.send_command(
            "RELEASE",
            timeout_ms=8000,
        ):
            raise RuntimeError(
                "RELEASE ACK failed"
            )

        time.sleep(args.settle)

        print()
        print(
            "PDO command sequence completed."
        )

        print(
            "Confirm that VBUS has returned "
            "to approximately 5 V."
        )

        return 0

    except KeyboardInterrupt:
        print()
        print(
            "Test interrupted by user."
        )

        return 130

    except Exception as error:
        print()
        print(
            f"ERROR: {error}"
        )

        return 1

    finally:
        if (
            kt002.device is not None
            and not release_attempted
        ):
            print()
            print(
                "Attempting emergency "
                "RELEASE to 5 V..."
            )

            try:
                kt002.send_command(
                    "RELEASE",
                    timeout_ms=8000,
                )

                time.sleep(2)

            except Exception as release_error:
                print(
                    "WARNING: RELEASE failed: "
                    f"{release_error}"
                )

        kt002.close()


if __name__ == "__main__":
    sys.exit(main())