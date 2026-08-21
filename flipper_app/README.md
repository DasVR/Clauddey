# Clauddey Flipper app

External FAP for official firmware, built with [ufbt](https://github.com/flipperdevices/flipperzero-ufbt).

## Build

```bash
ufbt update --channel=release
ufbt
ufbt launch
```

Requires firmware that exports USB CDC (`furi_hal_cdc_*`). The app switches USB to
`usb_cdc_dual` and talks on **CDC interface 1**.

## UI

1. **Menu** — Left/Right cycles Monitor, Interact, and Silent. OK starts a session. Back exits.
2. **Session** — Shows active agent, status, and a tiny log.
   - Back always returns to the menu (local only).
   - In **Monitor** mode, Up/Down scroll the local log. OK / Left / Right / long-Up do nothing remote.
   - In **Interactive** and **Silent** those keys emit a serial command through a single TX gate.
   - Silent keeps LED/OLED feedback but never runs the vibration motor.

## Files

| File | Role |
|------|------|
| `clauddey.c` | GUI, event loop, 3-way mode toggle, command gate |
| `clauddey_protocol.c` | JSON extractor + 64-byte CDC line assembler |
| `clauddey_serial.c` | USB CDC worker (ISR only sets flags; TX is chunked) |
