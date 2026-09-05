# Clauddey Host Bridge

Async Python daemon that:

1. Accepts real events from Claude Code hooks (`plugin/`), MCP clients
   (Claude Desktop, Cursor, ...), or anything else via a small IPC socket
2. Aggregates them into one v1 JSON status line (last non-idle agent wins)
3. Writes that line to the Flipper over USB CDC (BLE transport exists here
   too, but the Flipper firmware side isn't ported yet — see the root README)
4. Reads Flipper button commands and routes shortcuts by active agent, via a
   real Windows keystroke/dictation backend (`SendInput`/Win+H) or a
   log-only fallback elsewhere

Full clone-to-run steps (including Linux `dialout` and Windows COM notes) are in
the [root README install section](../README.md#install).

## Install

Python 3.10+ and `pip`:

```bash
cd host_bridge
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate.bat
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

## Run

Dry-run (no hardware) — this is the path exercised by CI:

```bash
python3 bridge.py --dry-run
```

With a Flipper running the Clauddey FAP (CDC interface 1, usually `ttyACM1`):

```bash
python3 bridge.py --port auto --transport auto
```

Or run it persistently in the background (Windows): see `install_startup.py`
and the root README's "Running it persistently" section.

Key flags: `--transport {auto,usb,ble}`, `--ipc-socket <path>` / `--no-ipc`,
`--mcp-port <port>` / `--no-mcp`.

The bridge auto-reconnects if the Flipper is unplugged or the Python process
loses the CDC port. ACM/COM numbers are rediscovered on each attempt, and the
last status payload is replayed after a successful (re)connect.

## Real agent integration

There is no more `--demo` scaffolding — real events come from:

* **Claude Code** — install `../plugin/` as a Claude Code plugin; its hooks
  push status over the IPC socket (`ipc_client.py`) whenever a session
  starts/ends, a prompt is submitted, a notification fires, or Claude stops.
  Permission-request-driven approve/deny via Flipper buttons isn't built yet
  (it needs a bidirectional protocol beyond the current fire-and-forget
  `notify` action) — everything else in the plugin's hook set is real and
  working.
* **Claude Desktop / Cursor / anything MCP-capable** — the bridge exposes a
  `clauddey_notify(agent, status, msg)` tool over streamable HTTP
  (`mcp_server.py`), since this is a long-running daemon serving possibly
  simultaneous clients, not a per-client stdio process.
* **Anything else** — connect to the IPC socket directly (`ipc_client.py`,
  or plain sockets) and send `{"action":"notify","agent":...,"status":...,"msg":...}`.

Keyboard chords are sent via a real backend on Windows
(`router.default_backends()` picks `input_win.Win32KeyBackend` /
`voice_win.Win32DictationBackend`) and logged-only elsewhere. Swap
`CommandRouter(backend=..., dictation=...)` for a different backend if you
want to target another platform.

## Tests

```bash
cd host_bridge
python3 -m unittest discover -s tests -v
```
