from core.doe_engine import DOEEngine

engine = DOEEngine()

engine.connect()

print("Please set AC Input to 115Vac")

input(
    "Press ENTER when ready..."
)

if engine.check_input_voltage(
        target_voltage=115,
        tolerance=2
):

    print("Voltage OK")

else:

    print("Voltage ERROR")

    engine.disconnect()

    exit()

result = engine.run_single_point(
    load_current=1.0
)

print(result)

engine.disconnect()