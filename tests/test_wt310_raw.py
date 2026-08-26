from drivers.wt310 import WT310

wt = WT310()

wt.connect()

print(wt.read_raw())

wt.disconnect()