/**
 * @file clauddey_protocol.c
 * @brief Heap-free JSON field scraping for the v1 Clauddey schema.
 *
 * Intentionally tiny: strstr + bounded copy. No recursion, no malloc, no
 * floating point. Extra JSON fields are ignored.
 */
#include "clauddey_protocol.h"

#include <string.h>
#include <stdio.h>

static bool str_eq(const char* a, const char* b) {
    if(!a || !b) return false;
    return strcmp(a, b) == 0;
}

ClauddeyAgent clauddey_agent_from_str(const char* s) {
    if(str_eq(s, "cursor") || str_eq(s, "cur")) return ClauddeyAgentCursor;
    if(str_eq(s, "claude") || str_eq(s, "cld")) return ClauddeyAgentClaude;
    return ClauddeyAgentNone;
}

ClauddeyStatus clauddey_status_from_str(const char* s) {
    if(str_eq(s, "thinking")) return ClauddeyStatusThinking;
    if(str_eq(s, "generating") || str_eq(s, "coding")) return ClauddeyStatusGenerating;
    if(str_eq(s, "waiting") || str_eq(s, "waiting_for_input") || str_eq(s, "approval")) {
        return ClauddeyStatusWaiting;
    }
    if(str_eq(s, "done") || str_eq(s, "complete") || str_eq(s, "success")) {
        return ClauddeyStatusDone;
    }
    if(str_eq(s, "error") || str_eq(s, "fail") || str_eq(s, "failed")) {
        return ClauddeyStatusError;
    }
    return ClauddeyStatusIdle;
}

const char* clauddey_agent_str(ClauddeyAgent agent) {
    switch(agent) {
    case ClauddeyAgentCursor:
        return "cursor";
    case ClauddeyAgentClaude:
        return "claude";
    default:
        return "none";
    }
}

const char* clauddey_status_str(ClauddeyStatus status) {
    switch(status) {
    case ClauddeyStatusThinking:
        return "thinking";
    case ClauddeyStatusGenerating:
        return "generating";
    case ClauddeyStatusWaiting:
        return "waiting";
    case ClauddeyStatusDone:
        return "done";
    case ClauddeyStatusError:
        return "error";
    default:
        return "idle";
    }
}

const char* clauddey_cmd_str(ClauddeyCmd cmd) {
    switch(cmd) {
    case ClauddeyCmdOk:
        return "ok";
    case ClauddeyCmdCancel:
        return "cancel";
    case ClauddeyCmdLeft:
        return "left";
    case ClauddeyCmdRight:
        return "right";
    case ClauddeyCmdUp:
        return "up";
    case ClauddeyCmdDown:
        return "down";
    case ClauddeyCmdDictate:
        return "dictate";
    default:
        return "none";
    }
}

/**
 * Copy the JSON string value for `"key":"..."` into out.
 * Handles a single escaped quote/backslash pair so truncated host messages
 * do not walk off the buffer. Not a full JSON string decoder.
 */
static bool extract_json_string(const char* json, const char* key, char* out, size_t out_sz) {
    if(!json || !key || !out || out_sz == 0) return false;

    char pattern[24];
    int n = snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    if(n <= 0 || (size_t)n >= sizeof(pattern)) return false;

    const char* k = strstr(json, pattern);
    if(!k) return false;

    const char* colon = strchr(k + (size_t)n, ':');
    if(!colon) return false;

    const char* q1 = strchr(colon, '"');
    if(!q1) return false;
    q1++;

    const char* q2 = q1;
    while(*q2 && *q2 != '"') {
        if(*q2 == '\\' && q2[1] != '\0') {
            q2 += 2;
            continue;
        }
        q2++;
    }
    if(*q2 != '"') return false;

    size_t len = (size_t)(q2 - q1);
    if(len >= out_sz) len = out_sz - 1;
    memcpy(out, q1, len);
    out[len] = '\0';
    return true;
}

bool clauddey_parse_status(const char* json, ClauddeyStatusMsg* out) {
    if(!json || !out) return false;
    memset(out, 0, sizeof(*out));

    char agent[12] = {0};
    char status[24] = {0};

    if(!extract_json_string(json, "agent", agent, sizeof(agent))) return false;
    if(!extract_json_string(json, "status", status, sizeof(status))) return false;

    out->agent = clauddey_agent_from_str(agent);
    out->status = clauddey_status_from_str(status);

    if(!extract_json_string(json, "msg", out->msg, sizeof(out->msg))) {
        out->msg[0] = '\0';
    }
    return true;
}

void clauddey_line_reset(ClauddeyLineBuf* buf) {
    if(!buf) return;
    buf->len = 0;
    buf->drop = false;
    buf->data[0] = '\0';
}

void clauddey_line_feed_bytes(
    ClauddeyLineBuf* buf,
    const uint8_t* data,
    size_t len,
    ClauddeyLineCallback cb,
    void* context) {
    if(!buf || !data) return;

    for(size_t i = 0; i < len; i++) {
        char c = (char)data[i];
        if(c == '\r') continue;

        if(c == '\n') {
            if(buf->drop) {
                clauddey_line_reset(buf);
                continue;
            }
            if(buf->len == 0) continue;
            buf->data[buf->len] = '\0';
            if(cb) cb(buf->data, context);
            clauddey_line_reset(buf);
            continue;
        }

        if(buf->drop) continue;

        /* Leave a byte for the NUL we write when the line completes. */
        if((size_t)buf->len + 1 >= sizeof(buf->data)) {
            buf->drop = true;
            buf->len = 0;
            continue;
        }
        buf->data[buf->len++] = c;
    }
}

size_t clauddey_format_command(char* out, size_t out_sz, ClauddeyCmd cmd, ClauddeyAgent agent) {
    if(!out || out_sz < 16 || cmd == ClauddeyCmdNone) return 0;

    /* mode is hard-coded: the caller must already have passed the TX gate. */
    int n = snprintf(
        out,
        out_sz,
        "{\"v\":%d,\"cmd\":\"%s\",\"agent\":\"%s\",\"mode\":\"interactive\"}\n",
        CLAUDDEY_PROTO_VERSION,
        clauddey_cmd_str(cmd),
        clauddey_agent_str(agent));

    if(n <= 0 || (size_t)n >= out_sz) {
        if(out_sz) out[0] = '\0';
        return 0;
    }
    return (size_t)n;
}
