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

ep_in = usb.util.find_descriptor(
    intf,
    bEndpointAddress=0x84
)

print("Listening...")

while True:

    try:

        data = ep_in.read(
            64,
            timeout=1000
        )

        print(
            bytes(data).hex()
        )

    except Exception:
        pass