with open("/dev/usbtmc0", "w") as f:
    f.write("*IDN?\n")

with open("/dev/usbtmc0", "r") as f:
    print(f.read())