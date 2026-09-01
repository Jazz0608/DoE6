import serial
import time

ser = serial.Serial(
    port="/dev/ttyUSB0",
    baudrate=9600,
    bytesize=8,
    parity="N",
    stopbits=1,
    timeout=1
)

ser.write(b"SYST:VERS?\n")

time.sleep(0.5)

data = ser.read_all()

print(data)

ser.close()