# Clauddey

Clauddey turns a Flipper Zero into a physical status display and remote
control for AI coding agents — **Claude Code**, **Claude Desktop**, **Cursor**,
or anything else that can push a status update or receive a keystroke. A
small FAP on the Flipper shows who's working and what they're doing; a
Python daemon on your machine keeps that display in sync and turns Flipper
button presses into real keystrokes in your editor or terminal.

```
                 ┌─────────────────────────┐
 Claude Code ───►│ hooks (plugin/)         │
 Claude Desktop ►│ MCP tool                ├──► Host Bridge (daemon) ──USB CDC──► Flipper
 Cursor ────────►│ MCP tool                │        ▲                              │
 anything else ─►│ raw IPC socket          │        └──── Interactive commands ◄────┘
                 └─────────────────────────┘             (blocked in Monitor mode)
```

The host bridge is a **persistent background daemon** (Windows: installs
itself into Startup, runs headless with a tray icon) — not something you
launch by hand every session. It reconnects on its own whenever the Flipper
is plugged in.

> **BLE status:** the host bridge already speaks BLE (`bleak`, via
> `--transport ble`/`auto`) against a generic Flipper serial-over-BLE
> peripheral, but the Clauddey Flipper *app* itself is still **USB-only** —
> porting the firmware side to BLE is tracked as future work (see
> [Roadmap](#roadmap)). Until then, USB is the only transport that actually
> reaches the Flipper end-to-end.

## Features

- **Status display** — agent name, status (thinking/generating/waiting/done/error),
  and a short message on the Flipper's OLED, with LED and haptic feedback.
- **Three modes** (cycle with Left/Right): **Monitor** (display only, no
  commands leave the device), **Interactive** (D-Pad/OK send real keystrokes
  back to the host), **Silent Interactive** (same, haptics off).
- **Real Claude Code integration** — a Claude Code plugin (`plugin/`) hooks
  session start/end, prompt submission, notifications, and stop events
  straight into the display, no demo data involved.
- **MCP tool for everything else** — `clauddey_notify(agent, status, msg)`
  over streamable HTTP, so Claude Desktop, Cursor, or any other MCP client
  can drive the display too.
- **Real keystrokes on Windows** — `SendInput`/Win+H via raw `ctypes`, no
  `pyautogui`/`pynput` dependency. Off Windows it currently falls back to
  logging only (see [Roadmap](#roadmap)).
- **Runs itself** — a singleton daemon (Win32 named mutex, not a pidfile —
  pidfiles are racy under Windows' fast PID reuse), auto-reconnect, a tray
  icon, and a one-line Startup installer.

## Install

You need a Flipper Zero on **official firmware**, Python **3.10+**, and `git`.

- **Windows:** see **[INSTALL_WINDOWS.md](INSTALL_WINDOWS.md)** for
  `ufbt launch`/COM-port specifics; the summary below still applies.
- **Linux / macOS:** follow the steps below directly.

### 1. Clone

```bash
git clone https://github.com/DasVR/Clauddey.git
cd Clauddey
```

### 2. Flash the Flipper app

```bash
python3 -m pip install --upgrade ufbt   # micro Flipper Build Tool
cd flipper_app
ufbt update --channel=release           # match your Flipper's firmware channel
ufbt
ufbt launch                             # builds dist/clauddey.fap and flashes it
```

If `ufbt launch` can't see the device, copy `flipper_app/dist/clauddey.fap`
onto the SD card under `apps/Tools/` (qFlipper → File manager works) and
launch **Clauddey** from **Apps → Tools** by hand.

The app switches USB to dual CDC and talks on **interface 1** (the second
virtual COM port) — start Clauddey on the Flipper *before* the host bridge.
See [Windows: `ufbt launch` and COM ports](#windows-ufbt-launch-and-com-ports)
below if the two COM ports confuse `ufbt`'s auto-detect.

### 3. Set up the host bridge

```bash
cd ../host_bridge
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate.bat
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

This installs `pyserial`, `pyserial-asyncio`, `bleak`, `mcp`, `uvicorn`, and
(Windows only) `pystray`/`Pillow` for the tray icon.

Smoke-test without hardware:

```bash
python3 bridge.py --dry-run
```

With the FAP running on the Flipper (any of the three modes), start the bridge:

```bash
python3 bridge.py --port auto --transport auto   # USB first, BLE fallback
python3 bridge.py --port COM5 --transport usb    # Windows: the *higher* COM of the pair
python3 bridge.py --port /dev/ttyACM1            # Linux
python3 bridge.py --port /dev/cu.usbmodemFLIP*   # macOS (tab-complete)
```

It reconnects automatically if the Flipper is unplugged — ACM/COM numbers
are rediscovered on every attempt.

### 4. Run it persistently instead (recommended, Windows)

Rather than starting `bridge.py` by hand every session:

```powershell
python install_startup.py            # adds a Startup-folder shortcut, runs it now too
python install_startup.py --uninstall  # removes it again
```

This runs `daemon.py` headlessly (`pythonw.exe`, no console window), guarded
by a singleton so only one instance ever runs, with a tray icon showing
connection status and a Quit item.

### 5. Wire up real agent events

- **Claude Code** — install the plugin so session/notification/stop events
  reach the Flipper for real:
  ```
  /plugin marketplace add DasVR/Clauddey
  /plugin install clauddey@clauddey
  ```
  Hooks only *push* status to the already-running daemon — they never start
  or stop it. (Approve/deny of permission prompts via Flipper buttons isn't
  built yet; see [Roadmap](#roadmap).)
- **Claude Desktop / Cursor / anything MCP-capable** — point it at
  `http://127.0.0.1:8787/mcp` (`--mcp-port` to change, `--no-mcp` to
  disable) and call the `clauddey_notify(agent, status, msg)` tool.
- **Anything else** — send `{"action":"notify","agent":...,"status":...,"msg":...}`
  to the IPC socket using `host_bridge/ipc_client.py`, or a plain socket
  connection (marker-file-based TCP on Windows, a real Unix socket
  elsewhere).

### Uninstall

- Flipper: delete `apps/Tools/clauddey.fap` from the SD card.
- Host: `python install_startup.py --uninstall` (if installed), then remove `host_bridge/.venv`.
- Claude Code: `/plugin uninstall clauddey`.
- Build tool: `python3 -m pip uninstall ufbt`.

## Usage

Button mapping in Interactive/Silent Interactive mode, routed by whichever
agent is currently active:

| Flipper key | Cursor | Claude |
|-------------|--------|--------|
| OK | Accept diff (Ctrl+Enter) | Enter / approve |
| Left | Reject / Escape | Ctrl+C |
| Right | Accept remaining | Cycle terminal windows |
| Up / Down | Previous / next item | Previous / next item |
| Long Up | Host OS dictation | Host OS dictation |

Manual test without any agent connected:

```bash
echo '{"action":"notify","agent":"claude","status":"waiting","msg":"test"}' \
    | python host_bridge/ipc_client.py <socket path>
```

## Windows: `ufbt launch` and COM ports

`py -m ufbt launch` has **no `-p COM4` flag** — extra tokens are treated as
scons targets. The real override is a scons variable:

```powershell
py -m ufbt launch
# if it says "More than one Flipper is attached":
py -m ufbt launch FLIP_PORT=COM5
```

Quit **qFlipper** (tray icon too) first — Windows gives a COM port to only
one program at a time. **While Clauddey is running it enables dual CDC**, so
Windows shows *two* Flipper COM ports and `ufbt`'s auto-detect errors with
"More than one Flipper is attached." That's one Flipper, not two — press
**Back** on the device until you're at the home screen (Clauddey must fully
exit), then retry, or pass `FLIP_PORT=` for the *lower* COM of the pair (the
CLI). The host bridge uses the *higher* COM once Clauddey is running.

If the log shows `Installing` / `Launching app` and then:
```
ClearCommError failed (PermissionError(13, 'The device does not recognize the command.'))
```
the FAP **did** install and start — that's just USB re-enumerating. Look at
the Flipper; open **Apps → Tools → Clauddey** if needed, then point the host
bridge at the second COM port.

### Linux serial permissions

```bash
sudo usermod -aG dialout "$USER"
# log out and back in (or reboot), then confirm:
groups
```

### Finding the port

| OS | Typical ports | Which one |
|----|---------------|-----------|
| Linux | `/dev/ttyACM0`, `/dev/ttyACM1` | Clauddey uses **ACM1** once the FAP is running |
| macOS | `/dev/cu.usbmodem*` | the second `cu.usbmodem` device |
| Windows | `COMn` pair in Device Manager | the **higher** COM number of the Flipper pair |

```bash
python3 -c "from serial.tools import list_ports; print([p.device for p in list_ports.comports()])"
```

## Layout

```
flipper_app/          ufbt FAP (Furi GUI + USB CDC; BLE not yet ported)
host_bridge/          Python daemon: transports, aggregator, router, IPC, MCP
plugin/               Claude Code plugin (hooks -> host_bridge's IPC)
.claude-plugin/        marketplace manifest for the plugin above
PROTOCOL.md           Newline-delimited JSON schema
examples/             Sample Cursor / Claude payloads
```

## Architecture notes

**Flipper (C):** no heap during JSON parse; a 160-byte line assembler spans
64-byte CDC packets until newline; GUI redraws are `view_port_update` from
the app thread; the draw callback holds a mutex for ≤25 ms and skips the
frame if busy. Remote TX is gated by a single C function
(`clauddey_try_send_command`) plus a host-side check that drops any frame
without `"mode":"interactive"`.

**Host (Python):** a single asyncio event loop drives USB/BLE transport
I/O, the IPC server, the MCP server, and command routing. Disconnects
trigger an auto-reconnect loop (`bridge.py`'s `pump()`) rather than killing
the process; the daemon replays the last known status after every
reconnect so the OLED never shows stale data.

## Roadmap

Not yet built, tracked for future sessions:

- **Permission-request approval via Flipper buttons** — needs a
  bidirectional protocol (register a pending decision, resolve it from the
  next button press) beyond the current fire-and-forget `notify` action.
- **Claude Desktop / Cursor MCP client-config wiring** — verifying the
  exact config shape each client expects for a local streamable-HTTP server
  (vs. a stdio-spawned one), plus a stdio shim if needed.
- **Firmware BLE port** — porting a serial-over-BLE GATT profile into
  `flipper_app/` so the already-BLE-capable host bridge has a real Flipper
  peripheral to talk to wirelessly. Real hardware testing required.
- **macOS/Linux keystroke and dictation backends** — currently Windows-only
  (`input_win.py`/`voice_win.py`); both platforms fall back to logging only.

## Tests

```bash
cd host_bridge
python3 -m unittest discover -s tests -v
cd ..

gcc -std=c11 -Wall -Wextra -Werror -I flipper_app \
    tests/test_clauddey_protocol.c flipper_app/clauddey_protocol.c \
    -o /tmp/clauddey_protocol_test && /tmp/clauddey_protocol_test
```
