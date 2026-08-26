import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from drivers.wt310 import WT310

wt = WT310()

wt.connect()

print(wt.query(":NUMERIC:NORMAL:VALUE?"))

wt.disconnect()