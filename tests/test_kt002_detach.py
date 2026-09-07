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

for i in [0, 1, 3, 4]:

    try:

        if dev.is_kernel_driver_active(i):

            print(
                f"Detach Interface {i}"
            )

            dev.detach_kernel_driver(i)

    except Exception as e:

        print(
            f"Interface {i}: {e}"
        )

print("Done")