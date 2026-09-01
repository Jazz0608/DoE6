import serial

ser = serial.Serial(
    port="/dev/ttyUSB0",
    baudrate=9600,
    timeout=1
)

print("Port Open =", ser.is_open)

ser.close()