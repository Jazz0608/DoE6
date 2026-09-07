import serial
import time

ser = serial.Serial(
    port="/dev/ttyACM0",
    baudrate=115200,
    timeout=1
)

print("Waiting...")

time.sleep(2)

data = ser.read_all()

print(data)

ser.close()