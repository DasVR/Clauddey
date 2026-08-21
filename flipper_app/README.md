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

1. **Menu** — Left/Right toggles Monitor vs Interactive. OK starts a session. Back exits.
2. **Session** — Shows active agent, status, and a tiny log.
   - Back always returns to the menu (local only).
   - Up/Down scroll the local log.
   - In **Monitor** mode, OK / Left / Right / long-Up do nothing remote.
   - In **Interactive** mode those keys emit a serial command through a single TX gate.

## Files

| File | Role |
|------|------|
| `clauddey.c` | GUI, event loop, mode toggle, command gate |
| `clauddey_protocol.c` | Tiny JSON field extractor (no heap) |
| `clauddey_serial.c` | USB CDC worker thread (ISR only sets flags) |
