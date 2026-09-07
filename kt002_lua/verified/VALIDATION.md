cat > kt002_lua/verified/VALIDATION.md <<'EOF'
# KT002 Direct USB Validation Record

## Version

- Lua baseline: onBoot_v1.0_fixed_pdo_verified.lua
- Python baseline: drivers/kt002_legacy_verified.py
- Status: Hardware verified

## Architecture

Raspberry Pi Python
-> USB direct connection
-> KT002 Shizuku Protocol
-> Lua_MOSI
-> tcp.onReceived()
-> pdSink.request()

Windows and KT Toolbox are not required during operation.

## Verified USB Parameters

- VID: 0x0483
- PID: 0xFFFF
- USB interface: 0
- Bulk OUT endpoint: 0x01
- Bulk IN endpoint: 0x81
- Frame start: 0xA5
- Frame end: 0x5A
- Check: XOR of payload

## Verified Protocol Results

- Shizuku PING reply: 0x80000009
- Lua_MOSI ACK: 0x80000000
- Lua received PING successfully
- KT002 displayed: Raspberry Pi connected

## Verified Fixed PDO Sequence

The following voltage sequence was verified using a supported PD charger
with the electronic load disconnected or OFF:

5V -> 9V -> 12V -> 15V -> 20V -> 5V

## Verified Requirements

- Raspberry Pi directly controls KT002 through USB
- Windows is not required
- KT Toolbox is not required
- onBoot.lua receives Raspberry Pi commands
- Multiple commands can be processed sequentially
- Fixed PDO selection searches Source Capabilities instead of using a
  hard-coded PDO index

## Not Yet Verified

- Unsupported PDO response
- No-PD-source error handling
- Charger unplug and reconnect
- Replacement with a different charger
- Lua MISO text result parsing in Python
- Long-duration reliability
- PDO switching under electronic load
- Chroma 6312A voltage verification
- WT310 integration
- AC source integration
EOF