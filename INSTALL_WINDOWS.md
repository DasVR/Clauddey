# Clauddey — Windows install

End-to-end setup for one Flipper Zero and one PC. Use **PowerShell**.
Commands assume the repo lives at `C:\Users\<you>\Clauddey`.

## What you will have

1. **Clauddey FAP** on the Flipper (`Apps → Tools → Clauddey`)
2. **Host bridge** Python script on the PC, talking USB serial

While Clauddey is running, Windows shows **two** COM ports for one Flipper
(stock CLI + Clauddey’s CDC). That is normal.

## 0. Prerequisites

Install these first, then reboot if Windows asks:

| Tool | Why | Where |
|------|-----|--------|
| [Git for Windows](https://git-scm.com/download/win) | clone / pull | default options are fine |
| [Python 3.10+](https://www.python.org/downloads/) | `ufbt` and the host bridge | **check** “Add python.exe to PATH” |
| [qFlipper](https://flipperzero.one/update) | official firmware + optional FAP copy | — |

In PowerShell, confirm:

```powershell
git --version
py --version
```

You want Python 3.10 or newer. Use `py` (the Windows launcher), not the
Store stub named `python` if that one is missing.

### Flipper firmware

1. Open **qFlipper**, connect the Flipper with a **data** USB-C cable (not charge-only).
2. Unlock the Flipper.
3. Update to **official release** firmware. Clauddey must be built for the **same
   channel** (`release` in the commands below). If you stay on `dev` / `rc`,
   change `--channel=` later to match.
4. **Quit qFlipper completely** (system tray too). Windows allows only one
   program to open a COM port at a time. Leave it closed whenever you run
   `ufbt` or `bridge.py`.

## 1. Clone

```powershell
cd $HOME
git clone https://github.com/DasVR/Clauddey.git
cd Clauddey
```

If you already cloned it:

```powershell
cd $HOME\Clauddey
git pull
```

## 2. Install `ufbt` and the SDK

```powershell
py -m pip install --upgrade pip ufbt
cd $HOME\Clauddey\flipper_app
py -m ufbt update --channel=release
```

The first `ufbt update` downloads the Windows toolchain (several hundred MB).
That is the “Extracting Windows toolchain” step.

## 3. Build and install the FAP

Unlock the Flipper. Leave it on the **home screen** (exit Clauddey if it is
already open — dual CDC makes `ufbt` think two Flippers are plugged in).

```powershell
cd $HOME\Clauddey\flipper_app
py -m ufbt
py -m ufbt launch
```

- `ufbt` writes `dist\clauddey.fap`
- `ufbt launch` copies it to `/ext/apps/Tools/clauddey.fap` and starts it

**Do not** pass `-p COM4`. That is not a `ufbt` flag. To force a port:

```powershell
py -m ufbt launch FLIP_PORT=COM5
```

Use the **lower** COM number of the Flipper pair (CLI). Find ports with:

```powershell
Get-CimInstance Win32_SerialPort |
  Select-Object DeviceID, Name, Description |
  Format-Table -AutoSize
```

Or Device Manager → **Ports (COM & LPT)**.

### If launch says `More than one Flipper is attached`

One Flipper is in dual-CDC (Clauddey still running). On the device press
**Back** until you are on the home screen, then `py -m ufbt launch` again.
Or pass `FLIP_PORT=COMx` for the CLI port.

### If launch says `Access is denied` on COMx

Something else owns the port: qFlipper, a leftover `bridge.py`, PuTTY, a
browser tab on lab.flipper.net. Close those, unplug/replug USB, retry.

### If launch installs then `ClearCommError`

The FAP **did install**. Clauddey re-enumerates USB. Open
**Apps → Tools → Clauddey** on the device and continue with the host bridge.

### Install without `ufbt launch`

1. Build: `py -m ufbt` → `flipper_app\dist\clauddey.fap`
2. Open qFlipper → **File manager** → copy the `.fap` to `SD card/apps/Tools/`
3. Quit qFlipper
4. On the Flipper: **Apps → Tools → Clauddey**

## 4. Host bridge

New PowerShell window (or the same one):

```powershell
cd $HOME\Clauddey\host_bridge
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

If Activate is blocked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

Smoke test (no Flipper required):

```powershell
py bridge.py --dry-run --demo
```

You should see mock Cursor then Claude JSON lines printed as `[serial tx]`.

## 5. First run with hardware

1. Unlock the Flipper, open **Apps → Tools → Clauddey**.
2. Left/Right: **Monitor**, **INTERACT**, or **SILENT**. OK to start a session.
3. Wait a couple of seconds (USB becomes two COM ports).
4. In the activated venv:

```powershell
cd $HOME\Clauddey\host_bridge
.\.venv\Scripts\Activate.ps1
py bridge.py --port auto --listen
```

If auto-detect picks the wrong port, use the **higher** COM of the pair:

```powershell
py bridge.py --port COM6 --listen
```

OLED should read **Host linked**. Optional canned statuses:

```powershell
py bridge.py --port auto --demo --listen
```

The bridge stays up if you undock. Plug the Flipper back in; it rediscovers
the COM port and replays the last status.

## 6. Daily use

```powershell
# 1. qFlipper closed, Flipper unlocked
# 2. Apps → Tools → Clauddey  (or ufbt launch if you rebuilt)

cd $HOME\Clauddey\host_bridge
.\.venv\Scripts\Activate.ps1
py bridge.py --port auto --listen
```

Rebuild after `git pull`:

```powershell
cd $HOME\Clauddey
git pull
cd flipper_app
# exit Clauddey on the device first
py -m ufbt launch
```

## 7. Which COM port is which

| When | How many COM ports | `ufbt launch` | `bridge.py` |
|------|--------------------|---------------|-------------|
| Home screen, Clauddey **not** running | 1 | that COM | — |
| Clauddey **running** | 2 | lower COM (CLI) if you must | **higher** COM |

`ufbt` talks to the Flipper CLI. The host bridge talks to Clauddey’s second
CDC interface.

## 8. Uninstall

- Flipper: delete `apps/Tools/clauddey.fap` on the SD card (qFlipper file manager).
- Host: `deactivate` then `Remove-Item -Recurse $HOME\Clauddey\host_bridge\.venv`
- Toolchain: `py -m pip uninstall ufbt`
- SDK cache: `%USERPROFILE%\.ufbt`

## 9. Button map (Interact / Silent)

| Flipper | Cursor | Claude |
|---------|--------|--------|
| OK | Accept diff (Ctrl+Enter) | Enter |
| Left | Escape / reject | Ctrl+C |
| Right | Accept remaining | Cycle windows |
| Up / Down | Previous / next | Previous / next |
| Long Up | Host OS dictation | Host OS dictation |

Monitor mode never sends those commands.
