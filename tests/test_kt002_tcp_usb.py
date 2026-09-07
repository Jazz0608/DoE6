import time
import usb.core
import usb.util

VID = 0x0483
PID = 0xFFFF

CONTROL_INTERFACE = 0
DATA_INTERFACE = 1

EP_OUT = 0x01
EP_IN = 0x81

dev = usb.core.find(
    idVendor=VID,
    idProduct=PID
)

if dev is None:
    raise RuntimeError("找不到 KT002")

# 必要時解除核心驅動
for interface in (CONTROL_INTERFACE, DATA_INTERFACE):
    try:
        if dev.is_kernel_driver_active(interface):
            dev.detach_kernel_driver(interface)
    except usb.core.USBError:
        pass

cfg = dev.get_active_configuration()
intf = cfg[(DATA_INTERFACE, 0)]

usb.util.claim_interface(dev, CONTROL_INTERFACE)
usb.util.claim_interface(dev, DATA_INTERFACE)

try:
    # CDC SET_LINE_CODING：115200、8N1
    line_coding = bytes([
        0x00, 0xC2, 0x01, 0x00,  # 115200，小端序
        0x00,                    # 1 stop bit
        0x00,                    # no parity
        0x08                     # 8 data bits
    ])

    dev.ctrl_transfer(
        0x21,
        0x20,
        0,
        CONTROL_INTERFACE,
        line_coding
    )

    # CDC SET_CONTROL_LINE_STATE：DTR + RTS
    dev.ctrl_transfer(
        0x21,
        0x22,
        0x0003,
        CONTROL_INTERFACE,
        None
    )

    # 清除先前 Pipe error 造成的 Endpoint Halt
    dev.clear_halt(EP_OUT)
    dev.clear_halt(EP_IN)

    time.sleep(0.5)

    print("發送：HELLO")

    written = dev.write(
        EP_OUT,
        b"HELLO\n",
        timeout=2000
    )

    print("已寫入位元組：", written)

    response = dev.read(
        EP_IN,
        64,
        timeout=3000
    )

    data = bytes(response)

    print("KT002 原始回覆：", data)
    print("KT002 文字回覆：", data.decode(errors="ignore"))

except usb.core.USBTimeoutError:
    print("KT002 讀取逾時：傳送成功，但沒有收到 Lua 回覆")

except usb.core.USBError as error:
    print("USB 錯誤：", error)

finally:
    # 關閉 DTR / RTS
    try:
        dev.ctrl_transfer(
            0x21,
            0x22,
            0x0000,
            CONTROL_INTERFACE,
            None
        )
    except usb.core.USBError:
        pass

    usb.util.release_interface(dev, DATA_INTERFACE)
    usb.util.release_interface(dev, CONTROL_INTERFACE)
    usb.util.dispose_resources(dev)
