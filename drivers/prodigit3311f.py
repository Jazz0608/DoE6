from drivers.base_load import BaseLoad


class Prodigit3311F(BaseLoad):

    def __init__(self,
                connection_type,
                address):

        self.connection_type = connection_type
        self.address = address

    def connect(self):
        print("3311F connect")

    def disconnect(self):
        print("3311F disconnect")

    def get_id(self):
        return "PRODIGIT 3311F"

    def set_cc(self):
        print("3311F CC Mode")

    def set_current(self, current):
        print(f"3311F Current={current}A")

    def load_on(self):
        print("3311F Load ON")

    def load_off(self):
        print("3311F Load OFF")