from drivers.kt002.controller import KT002Controller
from drivers.chroma6312 import Chroma6312
import time

print("=" * 72)
print("PDO Voltage Validation - Phase 7B")
print("=" * 72)

kt = KT002Controller()
load = Chroma6312()

try:
    print("Connecting KT002...")
    kt.connect()

    print("Connecting Chroma...")
    load.connect()

    print("Setting Chroma current = 0.5A")
    load.set_current(0.5)

    print("Requesting PDO 5V...")
    result = kt.set_voltage_result(5)

    print(f"KT002 Voltage = {result.measured_voltage:.3f}V")

    time.sleep(1)

    print("Load ON")
    load.load_on()

    time.sleep(1)

    chroma_voltage = load.read_voltage()
    chroma_current = load.read_current()
    chroma_power = load.read_power()

    print()
    print("Measurement Result")
    print("-" * 40)
    print(f"KT002 Voltage : {result.measured_voltage:.3f}V")
    print(f"Chroma Voltage: {chroma_voltage:.3f}V")
    print(f"Chroma Current: {chroma_current:.3f}A")
    print(f"Chroma Power  : {chroma_power:.3f}W")

finally:
    try:
        load.load_off()
    except Exception:
        pass

    try:
        kt.set_voltage_result(5)
    except Exception:
        pass

    try:
        load.disconnect()
    except Exception:
        pass

    try:
        kt.close()
    except Exception:
        pass

    print()
    print("Cleanup Complete")
