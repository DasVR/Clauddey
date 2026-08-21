/**
 * Host-side smoke test for flipper_app/clauddey_protocol.c (no Furi SDK required).
 *
 * gcc -std=c11 -Wall -Wextra -Werror -I flipper_app \
 *     tests/test_clauddey_protocol.c flipper_app/clauddey_protocol.c \
 *     -o /tmp/clauddey_protocol_test && /tmp/clauddey_protocol_test
 */
#include "clauddey_protocol.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    int count;
    char lines[8][CLAUDDEY_LINE_MAX];
} CapturedLines;

static void capture_line(const char* line, void* context) {
    CapturedLines* cap = context;
    assert(cap->count < 8);
    strncpy(cap->lines[cap->count], line, CLAUDDEY_LINE_MAX - 1);
    cap->lines[cap->count][CLAUDDEY_LINE_MAX - 1] = '\0';
    cap->count++;
}

static void feed_in_packets(ClauddeyLineBuf* buf, const char* text, size_t pkt, CapturedLines* cap) {
    size_t n = strlen(text);
    for(size_t off = 0; off < n; off += pkt) {
        size_t chunk = n - off;
        if(chunk > pkt) chunk = pkt;
        clauddey_line_feed_bytes(buf, (const uint8_t*)(text + off), chunk, capture_line, cap);
    }
}

static void test_parse_cursor(void) {
    ClauddeyStatusMsg msg;
    const char* json =
        "{\"v\":1,\"agent\":\"cursor\",\"status\":\"generating\",\"msg\":\"Generating code...\"}";
    assert(clauddey_parse_status(json, &msg));
    assert(msg.agent == ClauddeyAgentCursor);
    assert(msg.status == ClauddeyStatusGenerating);
    assert(strcmp(msg.msg, "Generating code...") == 0);
}

static void test_parse_claude_alias(void) {
    ClauddeyStatusMsg msg;
    const char* json =
        "{\"v\":1,\"agent\":\"claude\",\"status\":\"waiting_for_input\",\"msg\":\"Waiting for approval\"}";
    assert(clauddey_parse_status(json, &msg));
    assert(msg.agent == ClauddeyAgentClaude);
    assert(msg.status == ClauddeyStatusWaiting);
}

static void test_format_command_is_interactive(void) {
    char buf[80];
    size_t n = clauddey_format_command(buf, sizeof(buf), ClauddeyCmdOk, ClauddeyAgentCursor);
    assert(n > 0);
    assert(strstr(buf, "\"mode\":\"interactive\"") != NULL);
    assert(strstr(buf, "\"cmd\":\"ok\"") != NULL);
    assert(strstr(buf, "\"agent\":\"cursor\"") != NULL);
}

static void test_reject_garbage(void) {
    ClauddeyStatusMsg msg;
    assert(!clauddey_parse_status("not json", &msg));
    assert(!clauddey_parse_status("{\"status\":\"idle\"}", &msg));
}

static void test_line_spans_cdc_packets(void) {
    const char* frame =
        "{\"v\":1,\"agent\":\"cursor\",\"status\":\"generating\",\"msg\":\"Generating code...\"}\n";
    size_t n = strlen(frame);
    assert(n > CLAUDDEY_CDC_PKT_SZ);

    ClauddeyLineBuf buf;
    clauddey_line_reset(&buf);
    CapturedLines cap = {0};
    feed_in_packets(&buf, frame, CLAUDDEY_CDC_PKT_SZ, &cap);

    assert(cap.count == 1);
    ClauddeyStatusMsg msg;
    assert(clauddey_parse_status(cap.lines[0], &msg));
    assert(msg.agent == ClauddeyAgentCursor);
    assert(msg.status == ClauddeyStatusGenerating);
}

static void test_line_holds_state_across_tiny_chunks(void) {
    const char* frame = "{\"v\":1,\"agent\":\"claude\",\"status\":\"waiting\",\"msg\":\"hi\"}\n";
    ClauddeyLineBuf buf;
    clauddey_line_reset(&buf);
    CapturedLines cap = {0};
    feed_in_packets(&buf, frame, 1, &cap);
    assert(cap.count == 1);
    assert(strstr(cap.lines[0], "claude") != NULL);
}

static void test_overflow_resyncs_on_newline(void) {
    ClauddeyLineBuf buf;
    clauddey_line_reset(&buf);
    CapturedLines cap = {0};

    char huge[CLAUDDEY_LINE_MAX + 32];
    memset(huge, 'A', sizeof(huge) - 2);
    huge[sizeof(huge) - 2] = '\n';
    huge[sizeof(huge) - 1] = '\0';
    clauddey_line_feed_bytes(&buf, (const uint8_t*)huge, strlen(huge), capture_line, &cap);
    assert(cap.count == 0);

    const char* good = "{\"v\":1,\"agent\":\"cursor\",\"status\":\"idle\",\"msg\":\"ok\"}\n";
    clauddey_line_feed_bytes(&buf, (const uint8_t*)good, strlen(good), capture_line, &cap);
    assert(cap.count == 1);
    assert(strstr(cap.lines[0], "\"status\":\"idle\"") != NULL);
}

static void test_disconnect_drops_partial_line(void) {
    const char* prefix = "{\"v\":1,\"agent\":\"cursor\"";
    const char* rest = ",\"status\":\"idle\",\"msg\":\"x\"}\n";

    ClauddeyLineBuf glued;
    clauddey_line_reset(&glued);
    CapturedLines cap = {0};
    clauddey_line_feed_bytes(&glued, (const uint8_t*)prefix, strlen(prefix), capture_line, &cap);
    clauddey_line_feed_bytes(&glued, (const uint8_t*)rest, strlen(rest), capture_line, &cap);
    assert(cap.count == 1);
    assert(strstr(cap.lines[0], "cursor") != NULL);

    ClauddeyLineBuf isolated;
    clauddey_line_reset(&isolated);
    CapturedLines cap2 = {0};
    clauddey_line_feed_bytes(
        &isolated, (const uint8_t*)prefix, strlen(prefix), capture_line, &cap2);
    clauddey_line_reset(&isolated);
    clauddey_line_feed_bytes(&isolated, (const uint8_t*)rest, strlen(rest), capture_line, &cap2);
    assert(cap2.count == 1);
    assert(strstr(cap2.lines[0], "cursor") == NULL);
}

int main(void) {
    test_parse_cursor();
    test_parse_claude_alias();
    test_format_command_is_interactive();
    test_reject_garbage();
    test_line_spans_cdc_packets();
    test_line_holds_state_across_tiny_chunks();
    test_overflow_resyncs_on_newline();
    test_disconnect_drops_partial_line();
    puts("clauddey_protocol ok");
    return 0;
}
