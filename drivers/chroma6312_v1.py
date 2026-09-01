import serial
import time


class Chroma6312:

    def __init__(
        self,
        port="/dev/ttyUSB0",
        baudrate=9600,
        timeout=1
    ):

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None

    # -------------------------
    # Connection
    # -------------------------

    def connect(self):

        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=self.timeout
        )

        return self.ser.is_open

    def disconnect(self):

        if self.ser and self.ser.is_open:
            self.ser.close()

    # -------------------------
    # Basic Communication
    # -------------------------

    def write(self, cmd):

        self.ser.write(
            (cmd + "\n").encode()
        )

    def query(self, cmd):

        self.ser.reset_input_buffer()

        self.ser.write(
            (cmd + "\n").encode()
        )

        time.sleep(0.3)

        response = self.ser.read_all()

        return response.decode(
            errors="ignore"
        ).strip()

    # -------------------------
    # Device Information
    # -------------------------

    def get_id(self):

        return self.query("*IDN?")

    # -------------------------
    # Mode Control
    # -------------------------

    def get_mode(self):

        return self.query("MODE?")

    def set_mode_cch(self):

        self.write("MODE CCH")

    def set_mode_ccl(self):

        self.write("MODE CCL")

    def set_mode_cv(self):

        self.write("MODE CV")

    # Future
    # def set_mode_cr(self):
    #     self.write("MODE CR")

    # def set_mode_cp(self):
    #     self.write("MODE CP")

    # -------------------------
    # Load Control
    # -------------------------

    def load_on(self):

        self.write("LOAD ON")

    def load_off(self):

        self.write("LOAD OFF")

    def get_load_status(self):

        status = self.query("LOAD?")

        if status == "1":
            return True

        return False

    # -------------------------
    # Current Setting
    # -------------------------

    def set_current(self, current):

        self.write(
            f"CURR:STAT:L1 {current:.3f}"
        )

    def get_current_setting(self):

        value = self.query(
            "CURR:STAT:L1?"
        )

        return float(value)

    # -------------------------
    # Measurement
    # -------------------------

    def read_voltage(self):

        value = self.query(
            "MEAS:VOLT?"
        )

        return float(value)

    def read_current(self):

        value = self.query(
            "MEAS:CURR?"
        )

        return float(value)

    def read_power(self):

        value = self.query(
            "MEAS:POW?"
        )

        return float(value)

    # -------------------------
    # Summary
    # -------------------------

    def read_all(self):

        return {
            "voltage": self.read_voltage(),
            "current": self.read_current(),
            "power": self.read_power(),
            "mode": self.get_mode(),
            "load_status": self.get_load_status(),
            "current_setting": self.get_current_setting()
        }