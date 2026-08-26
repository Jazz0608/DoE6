import os

fd = os.open("/dev/usbtmc0", os.O_RDWR)

os.write(fd, b"*IDN?\n")

data = os.read(fd, 300)

print(data.decode())

os.close(fd)