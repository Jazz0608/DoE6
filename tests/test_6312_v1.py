from drivers.chroma6312_v1 import Chroma6312

load = Chroma6312()

print("Connect...")

load.connect()

print("ID =", load.get_id())

print("Mode =", load.get_mode())

# 切到 CC High
load.set_mode_cch()

print("Mode =", load.get_mode())

# 設定 5A
load.set_current(5.0)

print(
    "Current Setting =",
    load.get_current_setting()
)

# 開啟負載
load.load_on()

print(
    "Load Status =",
    load.get_load_status()
)

# 讀取量測值
print("Voltage =", load.read_voltage())
print("Current =", load.read_current())
print("Power   =", load.read_power())

# 一次讀全部
print(load.read_all())

# 關閉負載
load.load_off()

print(
    "Load Status =",
    load.get_load_status()
)

load.disconnect()

print("Done.")
