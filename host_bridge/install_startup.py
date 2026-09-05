#!/usr/bin/env python3
"""
One-time installer: creates a Windows Startup-folder shortcut that launches
the Clauddey daemon headlessly at login.

Run once after `pip install -r requirements.txt`:
    python install_startup.py
Remove it again with:
    python install_startup.py --uninstall
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HOST_BRIDGE_DIR = Path(__file__).resolve().parent


def _startup_dir() -> Path:
    appdata = Path(os.environ["APPDATA"])
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _pythonw_path() -> Path:
    venv_pythonw = HOST_BRIDGE_DIR / ".venv" / "Scripts" / "pythonw.exe"
    if venv_pythonw.exists():
        return venv_pythonw
    candidate = Path(sys.executable).with_name("pythonw.exe")
    if candidate.exists():
        return candidate
    return Path(sys.executable)  # last resort: python.exe (opens a console window)


def install() -> Path:
    if sys.platform != "win32":
        raise SystemExit("install_startup.py only supports Windows")

    startup_dir = _startup_dir()
    startup_dir.mkdir(parents=True, exist_ok=True)
    shortcut_path = startup_dir / "Clauddey.lnk"
    target = _pythonw_path()
    daemon_script = HOST_BRIDGE_DIR / "daemon.py"

    ps_script = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{target}"
$Shortcut.Arguments = '"{daemon_script}"'
$Shortcut.WorkingDirectory = "{HOST_BRIDGE_DIR}"
$Shortcut.Description = "Clauddey host bridge (background)"
$Shortcut.Save()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        check=True,
    )
    print(f"Installed startup shortcut: {shortcut_path}")
    print(f"  target: {target}")
    print(f"  args:   {daemon_script}")
    print("It will launch automatically the next time you log in.")
    print("To start it right now without logging out:")
    print(f'  & "{target}" "{daemon_script}"')
    return shortcut_path


def uninstall() -> None:
    shortcut_path = _startup_dir() / "Clauddey.lnk"
    if shortcut_path.exists():
        shortcut_path.unlink()
        print(f"Removed {shortcut_path}")
    else:
        print("No startup shortcut found (nothing to remove)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install/remove the Clauddey Startup shortcut")
    parser.add_argument("--uninstall", action="store_true", help="Remove the shortcut instead")
    args = parser.parse_args()
    if args.uninstall:
        uninstall()
    else:
        install()
    return 0


if __name__ == "__main__":
    sys.exit(main())
