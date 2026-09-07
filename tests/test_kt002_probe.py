import serial
import time

ser = serial.Serial(
    "/dev/ttyACM0",
    115200,
    timeout=1
)

commands = [
    b"\r\n",
    b"help\r\n",
    b"version\r\n",
    b"info\r\n",
    b"?\r\n",
]

for cmd in commands:

    print(f"Send: {cmd}")

    ser.write(cmd)

    time.sleep(1)

    data = ser.read_all()

    print("Response:", data)

ser.close()