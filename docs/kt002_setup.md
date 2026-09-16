# KT002 Linux Setup

## Device Information

KT002 USB Device

```text
VID = 0483
PID = FFFF

lsusb:
ID 0483:ffff STMicroelectronics Shizuku in Application Mode
```

---

## USB Permission Rule

File:

```text
/etc/udev/rules.d/99-kt002.rules
```

Content:

```text
ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="0483", ATTR{idProduct}=="ffff", MODE:="0666"
```

---

## Apply Rule

Reload udev rules:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Unplug and reconnect KT002 USB cable.

---

## Verify USB Device

```bash
lsusb
```

Expected:

```text
ID 0483:ffff STMicroelectronics Shizuku in Application Mode
```

Check permission:

```bash
ls -l /dev/bus/usb/<BUS>/<DEVICE>
```

Expected:

```text
crw-rw-rw-
```

---

## Symptoms

Without the udev rule:

```text
Unable to claim KT002 interface 0:
[Errno 13] Access denied (insufficient permissions)
```

KT002 test scripts may require:

```bash
sudo .venv/bin/python ...
```

which is not suitable for DOE6 automation.

---

## Validation

Test command:

```bash
.venv/bin/python -m tests.test_kt002_pdo_miso_all
```

Expected:

```text
PASS: full Fixed PDO Lua MISO regression completed
```

without sudo.

---

## Validation Result (2026-09-16)

Environment:

```text
Raspberry Pi 400
Python Virtual Environment (.venv)
KT002 Firmware: Shizuku in Application Mode
```

Command:

```bash
.venv/bin/python -m tests.test_kt002_pdo_miso_all
```

Result:

```text
PASS: full Fixed PDO Lua MISO regression completed

Verified:
5V -> 9V -> 12V -> 15V -> 20V -> 5V
```

Observed measurements:

```text
PD_5V  : 5.106V
PD_9V  : 8.905V
PD_12V : 11.895V
PD_15V : 14.914V
PD_20V : 20.035V
```

KT002 USB connection successfully opened and closed without sudo.

---

## Notes

This udev rule is required for:

```text
Phase 7  Chroma Integration
Phase 12 DOE6 State Machine
Phase 13 DOE Execution
Phase 17 CLI
Phase 18 GUI
```

to run under a normal user account without root privileges.

If Raspberry Pi OS is reinstalled or migrated to a new SD card,
this rule must be restored before using KT002.
