import usb.core

VID = 0x0483
PID = 0xffff

dev = usb.core.find(
    idVendor=VID,
    idProduct=PID
)

if dev is None:
    raise ValueError("KT002 Not Found")

for i in [0, 1, 2, 3, 4]:

    try:

        active = dev.is_kernel_driver_active(i)

        print(
            f"Interface {i}: "
            f"{active}"
        )

    except Exception as e:

        print(
            f"Interface {i}: {e}"
        )