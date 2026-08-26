from drivers.wt310 import WT310

wt = WT310()

wt.connect()

print("Voltage :", wt.read_voltage())
print("Current :", wt.read_current())
print("Power :", wt.read_power())
print("PF :", wt.read_pf())
print("Freq :", wt.read_frequency())

wt.disconnect()