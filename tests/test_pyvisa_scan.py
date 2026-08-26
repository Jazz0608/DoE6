import pyvisa

rm = pyvisa.ResourceManager()

print("Resource Manager:", rm)

resources = rm.list_resources()

print("Found Resources:")
for r in resources:
    print(r)