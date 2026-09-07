import usb.core
import usb.util

VID = 0x0483
PID = 0xffff

dev = usb.core.find(
    idVendor=VID,
    idProduct=PID
)

if dev is None:
    raise ValueError("KT002 Not Found")

cfg = dev.get_active_configuration()

intf = cfg[(4, 0)]

ep_out = usb.util.find_descriptor(
    intf,
    bEndpointAddress=0x04
)

ep_in = usb.util.find_descriptor(
    intf,
    bEndpointAddress=0x84
)

print("Send Test Packet...")

try:

    # 發送 64 Bytes 測試封包
    packet = bytes([0] * 64)

    ep_out.write(packet)

    print("TX OK")

    data = ep_in.read(
        64,
        timeout=1000
    )

    print("RX:", bytes(data).hex())

except Exception as e:

    print("ERROR:", e)