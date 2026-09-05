# Clauddey

Physical companion for **Claude** (Code / Desktop) and the **Cursor** IDE agent:
a Flipper Zero FAP plus a Python host bridge, now running as a persistent
background service with real Claude Code hook integration and an MCP surface
for anything else that can reach it.

```
 Claude Code hooks ──┐
 MCP clients (Desktop, Cursor, ...) ──► Host Bridge (daemon) ──USB CDC──► Flipper OLED + LED + vibro
                                            ▲                                │
                                            └──────── Interactive cmds ◄─────┘
                                                       (blocked in Monitor mode)
```

> **BLE status:** the host bridge already speaks BLE (`--transport ble`/`auto`)
> against a generic Flipper serial-over-BLE peripheral, but the Clauddey
> Flipper app itself is still **USB-only** — the firmware-side BLE port is a
> separate, not-yet-done piece of work. Until then, USB is the only transport
> that actually reaches the Flipper end-to-end.

## Install

- **Windows (PowerShell, COM ports, `ufbt launch`):** see **[INSTALL_WINDOWS.md](INSTALL_WINDOWS.md)**
- Linux / macOS: follow the steps below

You need a Flipper Zero on **official firmware**, Python **3.10+**, and `git`.
Build the FAP against the same firmware channel the device is running
(`release` in the commands below).

### 1. Clone

```bash
git clone https://github.com/DasVR/Clauddey.git
cd Clauddey
```

### 2. Flipper app (`ufbt`)

Install the [micro Flipper Build Tool](https://github.com/flipperdevices/flipperzero-ufbt):

```bash
python3 -m pip install --upgrade ufbt
```

(`pipx install ufbt` also works if you prefer an isolated tool install.)

Plug the Flipper in over USB, unlock it, then from the repo root:

```bash
cd flipper_app
ufbt update --channel=release
ufbt
ufbt launch
```

- `ufbt update` downloads the SDK that matches `--channel`.
- `ufbt` writes `dist/clauddey.fap`.
- `ufbt launch` copies the FAP onto the device and starts it.

If `ufbt launch` cannot see the device, copy `flipper_app/dist/clauddey.fap`
onto the SD card under `apps/Tools/` (qFlipper → **File manager** works) and
start **Clauddey** from **Apps → Tools**.

The app switches USB to dual CDC and talks on **interface 1** (the second
virtual COM port). Start Clauddey on the Flipper **before** the host bridge.

Match channels: if the Flipper is on `dev` or `rc` firmware, pass the same
value to `ufbt update --channel=...` or the FAP will refuse to load.

### 3. Host bridge (Python)

From the repo root:

```bash
cd host_bridge
python3 -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows (cmd)
# .venv\Scripts\activate.bat

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

That installs `pyserial`, `pyserial-asyncio`, `bleak`, `mcp`, `uvicorn`, and
(Windows only) `pystray`/`Pillow` for the tray icon. Smoke-test without
hardware:

```bash
python3 bridge.py --dry-run
```

With the FAP running, leave it in Monitor, Interact, or Silent and start the bridge:

```bash
# auto-picks the Flipper CDC port (prefers the second interface), USB first then BLE
python3 bridge.py --port auto --transport auto

# or set the port / transport explicitly
python3 bridge.py --port /dev/ttyACM1 --transport usb          # Linux
python3 bridge.py --port /dev/cu.usbmodemFLIP* --transport usb # macOS (tab-complete)
python3 bridge.py --port COM5 --transport usb                  # Windows; use the higher COM of the pair
```

The bridge waits and reconnects if the Flipper is unplugged. ACM/COM numbers
often change after re-enumeration; `--port auto` rediscovers them.

#### Running it persistently (Windows)

Rather than starting `bridge.py` by hand every session, install it as a
background daemon that launches at login:

```powershell
python install_startup.py            # one-time: adds a Startup-folder shortcut
python install_startup.py --uninstall  # removes it again
```

This runs `daemon.py` headlessly (`pythonw.exe`, no console window), guarded
by a singleton so only one instance ever runs, with a small tray icon showing
connection status and a Quit item. It reconnects automatically whenever the
Flipper is plugged in — no separate "start the bridge" step needed.

#### Claude Code / MCP integration

- **Claude Code**: install the `plugin/` directory as a Claude Code plugin
  (see `.claude-plugin/marketplace.json`) to get real session-start/end,
  prompt-submit, notification, and stop events pushed to the Flipper —
  replacing any need for manual demo data. It only *pushes* status to the
  already-running daemon; it never starts or stops it.
- **Anything MCP-capable** (Claude Desktop, Cursor, etc.): the bridge exposes
  a `clauddey_notify(agent, status, msg)` tool over streamable HTTP at
  `http://127.0.0.1:8787/mcp` by default (`--mcp-port` to change, `--no-mcp`
  to disable).
- **Anything else**: push `{"action":"notify","agent":...,"status":...,"msg":...}`
  to the IPC socket (a marker-file-based TCP endpoint on Windows, a real Unix
  socket elsewhere) using `host_bridge/ipc_client.py`, or plain sockets.

#### Linux serial permissions

Your user must be allowed to open the CDC device (usually `dialout` or `uucp`):

```bash
sudo usermod -aG dialout "$USER"
# log out and back in (or reboot), then confirm:
groups
```

#### Windows: `ufbt launch` and COM ports

`py -m ufbt launch` has **no `-p COM4` flag**. Extra tokens are treated as scons
targets. The real override is a scons variable:

```powershell
py -m ufbt launch
# if it says "More than one Flipper is attached":
py -m ufbt launch FLIP_PORT=COM5
```

Quit **qFlipper** (tray icon too) first. Windows gives a COM port to only one
program at a time.

**While Clauddey is running it enables dual CDC**, so Windows shows **two** Flipper
COM ports and `ufbt` auto-detect errors with `More than one Flipper is attached`.
That is one Flipper, not two. On the device press **Back** until you are on the
home screen (Clauddey must fully exit), then `py -m ufbt launch` again. Or pass
`FLIP_PORT=` for the **lower** COM of the pair (the CLI). The host bridge uses
the **higher** COM after Clauddey is running.

If the log shows `Installing` / `Launching app` and then:

```
ClearCommError failed (PermissionError(13, 'The device does not recognize the command.'))
```

the FAP **did install and start**. Look at the Flipper; open **Apps → Tools → Clauddey**
if needed. Then point the host bridge at the second COM port.

#### Finding the port

| OS | Typical ports | Which one |
|----|---------------|-----------|
| Linux | `/dev/ttyACM0`, `/dev/ttyACM1` | Clauddey uses **ACM1** once the FAP is running |
| macOS | `/dev/cu.usbmodem*` | the second `cu.usbmodem` device |
| Windows | `COMn` pair in Device Manager | the **higher** COM number of the Flipper pair |

```bash
# Linux
ls /dev/ttyACM*

# macOS
ls /dev/cu.usbmodem*

# any OS with pyserial
python3 -c "from serial.tools import list_ports; print([p.device for p in list_ports.comports()])"
```

### 4. First run

1. Unlock the Flipper and launch **Clauddey**.
2. Left/Right to **Monitor**, **Interact**, or **Silent**, then OK to start a session.
3. Start the host bridge (`--port auto`, or `install_startup.py` for a persistent daemon).
4. The OLED should show **Host linked**. Push a manual test status without any agent
   connected via `echo '{"action":"notify","agent":"claude","status":"waiting","msg":"test"}' | python ipc_client.py <socket path>`.

### Uninstall

- Flipper: delete `apps/Tools/clauddey.fap` from the SD card (qFlipper file manager or the on-device browser).
- Host: `python install_startup.py --uninstall` (if installed), then `deactivate` the venv and remove `host_bridge/.venv`.
- Build tool: `python3 -m pip uninstall ufbt`.

## Layout

```
flipper_app/          ufbt FAP (Furi GUI + USB CDC; BLE not yet ported)
host_bridge/          Python daemon: transports, aggregator, router, IPC, MCP
plugin/               Claude Code plugin (hooks -> host_bridge's IPC)
PROTOCOL.md           Newline-delimited JSON schema
examples/             Sample Cursor / Claude payloads
```

## Operating modes

The Flipper menu Left/Right cycles three modes:

| Mode | Visuals | Motor | Hardware buttons |
|------|---------|-------|------------------|
| **Monitor** | Agent name, status, LED (blue Cursor / purple Claude) | Short pulses on waiting / done / error | Local UI only: scroll logs, return to menu. **No commands leave the device.** |
| **Interactive** | Same | Same short haptics | D-Pad / OK send context-aware macros. Long-Up starts **host** dictation. |
| **Silent Interactive** | Same LED / OLED | **Off** (saves battery, no buzzing) | Same macros as Interactive. |

Remote TX is isolated by a single C function (`clauddey_try_send_command`) plus a host-side check that drops any frame without `"mode":"interactive"`. Silent still sends `mode=interactive` because silence is a local haptic setting.

## Quick start

After [install](#install), a typical hardware session is:

```bash
cd flipper_app && ufbt launch
cd ../host_bridge && source .venv/bin/activate  # Windows: .venv\Scripts\activate.bat
python3 bridge.py --port auto
```

Or, on Windows, run `python install_startup.py` once and never think about it again.

Button mapping (Interactive, routed by whichever agent is active):

| Flipper key | Cursor | Claude |
|-------------|--------|--------|
| OK | Accept diff (Ctrl+Enter) | Enter / approve |
| Left | Reject / Escape | Ctrl+C |
| Right | Accept remaining | Cycle terminal windows |
| Up / Down | Previous / next item | Previous / next item |
| Long Up | Host OS dictation | Host OS dictation |

On Windows, real keystrokes/dictation are sent via `SendInput`/Win+H
(`host_bridge/input_win.py`, `voice_win.py`) — no `pyautogui`/`pynput`
dependency. Off Windows, both still fall back to logging only.

## Memory / threading notes

Flipper: no heap during JSON parse; a 160-byte line assembler spans 64-byte CDC packets until newline; GUI redraws are `view_port_update` from the app thread; the draw callback holds a mutex for ≤25 ms and skips the frame if busy.

Host: a single asyncio event loop drives USB/BLE transport I/O, the IPC
server, the MCP server, and command routing; disconnects trigger an
auto-reconnect loop (`bridge.py`'s `pump()`) rather than killing the process.

## Tests

From the repo root:

```bash
cd host_bridge
python3 -m unittest discover -s tests -v
cd ..

gcc -std=c11 -Wall -Wextra -Werror -I flipper_app \
    tests/test_clauddey_protocol.c flipper_app/clauddey_protocol.c \
    -o /tmp/clauddey_protocol_test && /tmp/clauddey_protocol_test
```
