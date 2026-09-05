"""Environment-driven tunables for the Clauddey host bridge.

Only BLE-related settings live here for now; USB port/baud are plain CLI args
(see bridge.py's --port/--baud) since they vary per-invocation more than
per-machine.
"""

from __future__ import annotations

import os

# 16-bit service UUID every Flipper advertises; used to find it during a BLE scan.
FLIPPER_ADV_UUID = "00003082-0000-1000-8000-00805f9b34fb"

# Fallback match when an OS BLE stack strips service UUIDs from its ad cache.
BT_DEVICE_NAME = os.environ.get("CLAUDDEY_BT_NAME", "Flipper")

BT_SCAN_TIMEOUT = float(os.environ.get("CLAUDDEY_BT_SCAN_TIMEOUT", "10"))

# GATT write chunk cap; the actual chunk is min(this, negotiated_mtu - 3).
BT_WRITE_CHUNK = 128

# "auto" | "usb" | "ble" — overridable default for bridge.py's --transport flag.
TRANSPORT = os.environ.get("CLAUDDEY_TRANSPORT", "auto")
