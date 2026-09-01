from drivers.base_load import BaseLoad

class Chroma6312(BaseLoad):

    def __init__(self,
                connection_type,
                address):


        self.connection_type = connection_type
        self.address = address

    def connect(self):
        print("6312 connect")

    def disconnect(self):
        print("6312 disconnect")

    def get_id(self):
        return "CHROMA 6312A"

    def set_cc(self):
        print("6312 CC Mode")

    def set_current(self, current):
        print(f"6312 Current={current}A")

    def load_on(self):
        print("6312 Load ON")

    def load_off(self):
        print("6312 Load OFF")