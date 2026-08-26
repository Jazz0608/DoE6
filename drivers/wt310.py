# drivers/wt310.py

import os


class WT310:

    def __init__(self):
        self.device = "/dev/usbtmc0"
        self.fd = None

    def connect(self):
        self.fd = os.open(self.device, os.O_RDWR)

    def disconnect(self):
        if self.fd:
            os.close(self.fd)

    def query(self, cmd):
        os.write(self.fd, f"{cmd}\n".encode())
        data = os.read(self.fd, 1024)
        return data.decode().strip()

    def get_id(self):
        return self.query("*IDN?")

    def read_raw(self):
        return self.query(":NUMERIC:NORMAL:VALUE?")

    def read_all(self):

        raw = self.query(":NUMERIC:NORMAL:VALUE?")

        values = [float(v) for v in raw.split(",")]

        return {
            "voltage": values[0],
            "current": values[1],
            "power": values[2],
            "apparent_power": values[3],
            "reactive_power": values[4],
            "power_factor": values[5],
            "frequency": values[7]
        }