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

print("Connected to 6312A")
print("Type 'exit' to quit")
print("-" * 40)

while True:

    cmd = input("SCPI> ")

    if cmd.lower() == "exit":
        break

    ser.reset_input_buffer()

    ser.write((cmd + "\n").encode())

    time.sleep(0.5)
    
    response = ser.read_all()

    if response:
        print(response.decode(errors="ignore"))
    else:
        print("[No Response]")

ser.close()