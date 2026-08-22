# Clauddey

Physical companion for **Claude** (Code / Desktop) and the **Cursor** IDE agent:
a Flipper Zero FAP plus a Python host bridge over USB serial.

```
 Claude / Cursor ──► Host Bridge ──USB CDC──► Flipper OLED + LED + vibro
                         ▲                         │
                         └── Interactive cmds ◄────┘
                             (blocked in Monitor mode)
```

## Install

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

That installs `pyserial`. Smoke-test without hardware:

```bash
python3 bridge.py --dry-run --demo
```

With the FAP running, leave it in Monitor, Interact, or Silent and start the bridge:

```bash
# auto-picks the Flipper CDC port (prefers the second interface)
python3 bridge.py --port auto --listen

# or set the port explicitly
python3 bridge.py --port /dev/ttyACM1 --listen          # Linux
python3 bridge.py --port /dev/cu.usbmodemFLIP* --listen # macOS (tab-complete)
python3 bridge.py --port COM5 --listen                  # Windows; use the higher COM of the pair
```

The bridge waits and reconnects if the Flipper is unplugged. ACM/COM numbers
often change after re-enumeration; `--port auto` rediscovers them.

#### Linux serial permissions

Your user must be allowed to open the CDC device (usually `dialout` or `uucp`):

```bash
sudo usermod -aG dialout "$USER"
# log out and back in (or reboot), then confirm:
groups
```

#### Windows: `ufbt launch` and COM ports

`py -m ufbt launch` has **no `-p COM4` flag**. Extra tokens are treated as scons
targets (`Do not know how to make File target COM4`). Let ufbt auto-pick the port:

```powershell
py -m ufbt launch
```

Quit **qFlipper** (tray icon too) first. Windows gives a COM port to only one
program at a time.

If the log shows `Installing` / `Launching app` and then:

```
ClearCommError failed (PermissionError(13, 'The device does not recognize the command.'))
```

the FAP **did install and start**. Clauddey switches USB to dual CDC, so the old
COM handle dies. Look at the Flipper screen; open **Apps → Tools → Clauddey** if
it is not already up. Then run the host bridge on the **new** second COM port
(Device Manager will show a pair).

Current Clauddey waits ~1.5s after launch before changing USB so `ufbt launch`
can exit cleanly. Pull latest `main` and rebuild if you still hit ClearCommError
on every launch.

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
3. Start the host bridge (`--port auto --listen`).
4. The OLED should show **Host linked**. `--demo` injects mock Cursor and Claude events if you want a canned status sequence.

### Uninstall

- Flipper: delete `apps/Tools/clauddey.fap` from the SD card (qFlipper file manager or the on-device browser).
- Host: `deactivate` the venv and remove `host_bridge/.venv`.
- Build tool: `python3 -m pip uninstall ufbt`.

## Layout

```
flipper_app/          ufbt FAP (Furi GUI + USB CDC)
host_bridge/          Python aggregator + command router
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
cd ../host_bridge && source .venv/bin/activate
python3 bridge.py --port auto --demo --listen
```

Button mapping (Interactive, routed by whichever agent is active):

| Flipper key | Cursor | Claude |
|-------------|--------|--------|
| OK | Accept diff (Ctrl+Enter) | Enter / approve |
| Left | Reject / Escape | Ctrl+C |
| Right | Accept remaining | Cycle terminal windows |
| Up / Down | Previous / next item | Previous / next item |
| Long Up | Host OS dictation | Host OS dictation |

## Memory / threading notes

Flipper: no heap during JSON parse; a 160-byte line assembler spans 64-byte CDC packets until newline; GUI redraws are `view_port_update` from the app thread; the draw callback holds a mutex for ≤25 ms and skips the frame if busy.

Host: serial reads run on a daemon thread; writes are chunked to 64 bytes; disconnects trigger an auto-reconnect loop rather than killing the process.

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
