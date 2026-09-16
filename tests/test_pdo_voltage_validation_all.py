from drivers.kt002.controller import KT002Controller
from drivers.chroma6312 import Chroma6312
import time

PDO_LIST = [5, 9, 12, 15, 20]

print("=" * 72)
print("PDO Voltage Validation - ALL PDO")
print("=" * 72)

kt = KT002Controller()
load = Chroma6312()

results = []

try:
    print("Connecting KT002...")
    kt.connect()

    print("Connecting Chroma...")
    load.connect()

    print("Setting Chroma current = 0.5A")
    load.set_current(0.5)

    print("Load ON")
    load.load_on()

    for voltage in PDO_LIST:
        print()
        print(f"Requesting PDO {voltage}V...")

        result = kt.set_voltage_result(voltage)

        time.sleep(1)

        chroma_voltage = load.read_voltage()
        chroma_current = load.read_current()
        chroma_power = load.read_power()

        results.append(
            {
                "pdo": voltage,
                "kt002_voltage": result.measured_voltage,
                "chroma_voltage": chroma_voltage,
                "current": chroma_current,
                "power": chroma_power,
            }
        )

        print(
            f"KT002={result.measured_voltage:.3f}V "
            f"Chroma={chroma_voltage:.3f}V "
            f"I={chroma_current:.3f}A "
            f"P={chroma_power:.3f}W"
        )

    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)

    print(
        f"{'PDO':<8}"
        f"{'KT002(V)':<12}"
        f"{'Chroma(V)':<12}"
        f"{'Current(A)':<12}"
        f"{'Power(W)':<12}"
    )

    for row in results:
        print(
            f"{row['pdo']}V".ljust(8) +
            f"{row['kt002_voltage']:.3f}".ljust(12) +
            f"{row['chroma_voltage']:.3f}".ljust(12) +
            f"{row['current']:.3f}".ljust(12) +
            f"{row['power']:.3f}".ljust(12)
        )

finally:
    print()
    print("Cleanup...")

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

    print("Cleanup Complete")