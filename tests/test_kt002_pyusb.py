import usb.core
import usb.util

# KT002
VID = 0x0483
PID = 0xffff

dev = usb.core.find(
    idVendor=VID,
    idProduct=PID
)

if dev is None:
    print("KT002 Not Found")
    exit()

print("KT002 Found")

print(
    f"VID={hex(dev.idVendor)} "
    f"PID={hex(dev.idProduct)}"
)

for cfg in dev:

    print(
        f"\nConfiguration: "
        f"{cfg.bConfigurationValue}"
    )

    for intf in cfg:

        print(
            f"Interface: "
            f"{intf.bInterfaceNumber}"
        )

        for ep in intf:

            print(
                f" EP: {hex(ep.bEndpointAddress)}"
            )