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

print("KT002 Found")

try:

    dev.set_configuration()

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

    print("EP OUT =", ep_out)
    print("EP IN  =", ep_in)

except Exception as e:

    print(e)