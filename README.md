# Clauddey

Physical companion for **Claude** (Code / Desktop) and the **Cursor** IDE agent:
a Flipper Zero FAP plus a Python host bridge over USB serial.

```
 Claude / Cursor ──► Host Bridge ──USB CDC──► Flipper OLED + LED + vibro
                         ▲                         │
                         └── Interactive cmds ◄────┘
                             (blocked in Monitor mode)
```

## Layout

```
flipper_app/          ufbt FAP (Furi GUI + USB CDC)
host_bridge/          Python aggregator + command router
PROTOCOL.md           Newline-delimited JSON schema
examples/             Sample Cursor / Claude payloads
```

## Operating modes

The Flipper menu is a two-position toggle:

| Mode | Visuals / haptics | Hardware buttons |
|------|-------------------|------------------|
| **Monitor** | Agent name, status, LED color (blue Cursor / purple Claude), vibro on transitions | Local UI only: scroll logs, return to menu. **No commands leave the device.** |
| **Interactive** | Same feedback | D-Pad / OK send context-aware macros to the host. Long-Up starts **host** dictation (Flipper has no mic). |

Remote TX is isolated by a single C function (`clauddey_try_send_command`) plus a host-side check that drops any frame without `"mode":"interactive"`.

## Quick start

### Flipper

```bash
cd flipper_app
ufbt update --channel=release
ufbt
ufbt launch
```

The FAP switches USB to dual CDC and speaks on **interface 1** (often `/dev/ttyACM1`).

### Host bridge

```bash
cd host_bridge
pip install -r requirements.txt
python3 bridge.py --dry-run --demo
python3 -m unittest discover -s tests -v
```

The Flipper JSON parser can be compiled on a desktop (no SDK):

```bash
gcc -std=c11 -Wall -Wextra -Werror -I flipper_app \
    tests/test_clauddey_protocol.c flipper_app/clauddey_protocol.c \
    -o /tmp/clauddey_protocol_test && /tmp/clauddey_protocol_test
```

On hardware, start the FAP first (so CDC1 appears), then:

```bash
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

Flipper: no heap during JSON parse; fixed log lines; CDC ISR only sets thread flags; GUI redraws are `view_port_update` from the app thread; the draw callback holds a mutex for ≤25 ms and skips the frame if busy.

Host: serial reads run on a daemon thread; the main loop never blocks on `read()`.
