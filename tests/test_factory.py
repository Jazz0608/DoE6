from drivers.load_factory import LoadFactory


load = LoadFactory.create(
    model="6312A",
    connection_type="RS232",
    address="/dev/ttyUSB0"
)

load.connect()

print(load.get_id())

load.set_cc()

load.set_current(5)

load.load_on()

load.load_off()

load.disconnect()