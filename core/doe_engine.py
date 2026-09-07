from drivers.wt310 import WT310
from drivers.chroma6312 import Chroma6312
import time


class DOEEngine:

    def __init__(self):

        self.wt = WT310()

        self.load = Chroma6312()

    def connect(self):

        self.wt.connect()

        self.load.connect()

    def disconnect(self):

        self.load.disconnect()

        self.wt.disconnect()

    def check_input_voltage(
        self,
        target_voltage,
        tolerance=2
    ):

        vin = self.wt.read_voltage()

        lower = target_voltage - tolerance
        upper = target_voltage + tolerance

        return lower <= vin <= upper

    def run_single_point(
        self,
        load_current
    ):

        self.load.set_mode_cch()

        self.load.set_current(
            load_current
        )

        self.load.load_on()

        time.sleep(3)

        data = self.wt.read_all()

        self.load.load_off()

        return data