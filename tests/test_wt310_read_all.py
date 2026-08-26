from drivers.wt310 import WT310

wt = WT310()

wt.connect()

data = wt.read_all()

print(data)

wt.disconnect()