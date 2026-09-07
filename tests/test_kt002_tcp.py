import serial
import time

ser = serial.Serial(
    port="/dev/ttyACM0",
    baudrate=115200,
    timeout=2
)

time.sleep(1)

ser.reset_input_buffer()

ser.write(b"PD_20V\n")

print("已送出：PD_20V")

time.sleep(2)

response = ser.read_all()

print("KT002 回覆：", response)

ser.close()