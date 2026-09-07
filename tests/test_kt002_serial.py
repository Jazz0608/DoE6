import serial

ser = serial.Serial(
    port="/dev/ttyACM0",
    baudrate=115200,
    timeout=1
)

print("Open =", ser.is_open)

ser.close()