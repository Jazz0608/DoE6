import pyvisa

print("=" * 40)
print("Scan VISA Instruments")
print("=" * 40)

rm = pyvisa.ResourceManager()

resources = rm.list_resources()

if not resources:
    print("No VISA instrument found")
else:
    for item in resources:
        print(item)