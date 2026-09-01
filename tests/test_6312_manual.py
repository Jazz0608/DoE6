import serial
import time

ser = serial.Serial(
    "/dev/ttyUSB0",
    baudrate=9600,
    timeout=1
)

# CC Mode
ser.write(b"MODE C\n")

time.sleep(0.5)

# Set 1A
ser.write(b"CURR:STAT:L1 1\n")

time.sleep(0.5)

# Load ON
ser.write(b"LOAD ON\n")

print("Done")

ser.close()