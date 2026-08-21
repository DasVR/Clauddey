/**
 * @file clauddey_protocol.h
 * @brief Tiny shared protocol types and a heap-free JSON extractor.
 *
 * Payloads are newline-delimited JSON under ~120 bytes. This parser only
 * understands the v1 Clauddey schema — it is not a general JSON library.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CLAUDDEY_PROTO_VERSION 1
#define CLAUDDEY_MSG_MAX 40
#define CLAUDDEY_LINE_MAX 160
#define CLAUDDEY_TX_MAX 80
/** USB CDC bulk packet size. Lines longer than this arrive in multiple RX events. */
#define CLAUDDEY_CDC_PKT_SZ 64

/**
 * Stateful newline assembler. Holds a partial JSON line across 64-byte CDC
 * packets until `\n`. On overflow, bytes are discarded until the next newline
 * so a later well-formed line can resync.
 */
typedef struct {
    char data[CLAUDDEY_LINE_MAX];
    uint16_t len;
    bool drop;
} ClauddeyLineBuf;

typedef void (*ClauddeyLineCallback)(const char* line, void* context);

void clauddey_line_reset(ClauddeyLineBuf* buf);
void clauddey_line_feed_bytes(
    ClauddeyLineBuf* buf,
    const uint8_t* data,
    size_t len,
    ClauddeyLineCallback cb,
    void* context);

typedef enum {
    ClauddeyAgentNone = 0,
    ClauddeyAgentCursor,
    ClauddeyAgentClaude,
} ClauddeyAgent;

typedef enum {
    ClauddeyStatusIdle = 0,
    ClauddeyStatusThinking,
    ClauddeyStatusGenerating,
    ClauddeyStatusWaiting,
    ClauddeyStatusDone,
    ClauddeyStatusError,
} ClauddeyStatus;

typedef enum {
    ClauddeyCmdNone = 0,
    ClauddeyCmdOk,
    ClauddeyCmdCancel,
    ClauddeyCmdLeft,
    ClauddeyCmdRight,
    ClauddeyCmdUp,
    ClauddeyCmdDown,
    ClauddeyCmdDictate,
} ClauddeyCmd;

typedef struct {
    ClauddeyAgent agent;
    ClauddeyStatus status;
    char msg[CLAUDDEY_MSG_MAX + 1];
} ClauddeyStatusMsg;

/** Map wire strings to enums. Unknown values become None/Idle. */
ClauddeyAgent clauddey_agent_from_str(const char* s);
ClauddeyStatus clauddey_status_from_str(const char* s);
const char* clauddey_agent_str(ClauddeyAgent agent);
const char* clauddey_status_str(ClauddeyStatus status);
const char* clauddey_cmd_str(ClauddeyCmd cmd);

/**
 * Parse a single status JSON object (no trailing newline required).
 * Returns false if agent+status cannot be recovered. `msg` may be empty.
 */
bool clauddey_parse_status(const char* json, ClauddeyStatusMsg* out);

/**
 * Format a command line into `out` (including trailing newline).
 * Returns bytes written (excluding NUL), or 0 on failure.
 */
size_t clauddey_format_command(
    char* out,
    size_t out_sz,
    ClauddeyCmd cmd,
    ClauddeyAgent agent);

#ifdef __cplusplus
}
#endif
