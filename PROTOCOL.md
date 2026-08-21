# Clauddey serial protocol

Newline-delimited JSON over USB CDC. Keep payloads ASCII and under 120 bytes so a Flipper
can reassemble them from 64-byte USB packets without extra heap.

Default serial settings: **115200 8N1**. USB CDC ignores baud on the wire; 115200 is for
host libraries and GPIO-UART fallbacks.

Flipper CDC interface **1** (the second virtual COM port) is used so the stock CLI can
remain on interface 0. On Linux this is typically `/dev/ttyACM1` after the app starts.

## Status (host → Flipper)

Sent whenever the active agent changes, or its status/message changes.

```json
{"v":1,"agent":"cursor","status":"generating","msg":"Generating code..."}
```

| Field    | Values                                                                 |
|----------|------------------------------------------------------------------------|
| `v`      | Protocol version. Currently `1`.                                       |
| `agent`  | `cursor` \| `claude` \| `none`                                         |
| `status` | `idle` \| `thinking` \| `generating` \| `waiting` \| `done` \| `error` |
| `msg`    | Short ASCII status line, max ~40 characters.                           |

The `agent` field is the **active** agent: the one shown on the OLED and the one that
will receive Interactive-mode commands.

## Command (Flipper → host)

**Never sent in Monitor mode.** The Flipper firmware has a single TX gate; the host
also drops frames that are missing `"mode":"interactive"`.

```json
{"v":1,"cmd":"ok","agent":"cursor","mode":"interactive"}
```

| `cmd`     | Typical Cursor routing        | Typical Claude routing        |
|-----------|-------------------------------|-------------------------------|
| `ok`      | Accept diff / Ctrl+Enter      | Enter / approve               |
| `cancel`  | Escape / reject               | Ctrl+C                        |
| `right`   | Accept remaining / next hunk  | Cycle terminal windows        |
| `left`    | Reject / previous hunk        | Back / cancel secondary       |
| `up`      | Previous item                 | Previous item                 |
| `down`    | Next item                     | Next item                     |
| `dictate` | Host OS dictation (host mic)  | Host OS dictation (host mic)  |

`dictate` must start **computer-side** speech-to-text. The Flipper has no microphone
and must not record audio.

## Framing

- One JSON object per line, terminated by `\n` (optional `\r` is ignored).
- No pretty-print whitespace required.
- If a line is truncated or overflows the Flipper RX buffer, it is dropped until the
  next newline.
