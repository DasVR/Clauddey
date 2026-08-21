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

int main(void) {
    test_parse_cursor();
    test_parse_claude_alias();
    test_format_command_is_interactive();
    test_reject_garbage();
    puts("clauddey_protocol ok");
    return 0;
}
