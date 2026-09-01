from drivers.chroma6312 import Chroma6312

load = Chroma6312()

load.connect()

print(load.get_id())

load.set_mode_cch()

print(load.get_mode())

load.set_current(5.0)

print(load.get_current_setting())

load.load_on()

print(load.get_load_status())

load.load_off()

print(load.get_load_status())

load.disconnect()