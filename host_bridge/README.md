# Clauddey Host Bridge

Lightweight Python service that:

1. Accepts vendor-specific Cursor / Claude events through `AgentInterface`
2. Aggregates them into one v1 JSON status line
3. Writes that line to the Flipper over USB CDC
4. Reads Flipper button commands and routes shortcuts by active agent

## Setup

```bash
cd host_bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

Dry-run demo (no hardware) — this is the path exercised by CI:

```bash
python3 bridge.py --dry-run --demo
```

With a Flipper running the Clauddey FAP (CDC interface 1, usually `ttyACM1`):

```bash
python3 bridge.py --port auto --demo --listen
```

## Dummy vs real agents

`CursorAgent.parse_raw` and `ClaudeAgent.parse_raw` already normalize the mock
payloads in `../examples/sample_payloads.json`. Swap `poll()` for:

* **Claude Code** — tail session logs or hook the CLI
* **Cursor** — a tiny editor extension posting local HTTP/websocket events

Keyboard chords are logged by default. Plug a live backend into
`CommandRouter(backend=...)` when you want real keystrokes. Dictation macros
must trigger the **host** microphone; the Flipper never records audio.

## Tests

```bash
cd host_bridge
python3 -m unittest discover -s tests -v
```
