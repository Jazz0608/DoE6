import serial
import time

ser = serial.Serial(
    "/dev/ttyACM0",
    115200,
    timeout=1
)

def send_hex(hex_cmd):

    cmd_bytes = bytes.fromhex(hex_cmd)

    print("TX:", cmd_bytes.hex())

    ser.write(cmd_bytes)

    time.sleep(0.2)

    data = ser.read_all()

    print("RX:", data.hex())

    return data


# 測試封包
send_hex("0A010000000B")

ser.close()