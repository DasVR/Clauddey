/**
 * @file clauddey.c
 * @brief Clauddey GUI: Monitor / Interactive toggle and the remote-command gate.
 *
 * State machine (all remote TX goes through clauddey_try_send_command):
 *
 *     MENU  --OK-->  SESSION
 *      ^               |
 *      +----- Back ----+
 *
 *   MENU:        Left/Right toggles mode. No serial commands.
 *   SESSION+MON: Back exits, Up/Down scroll logs. Buttons never TX.
 *   SESSION+INT: same local UI, plus OK/Left/Right/long-Up emit commands.
 */

#include "clauddey_protocol.h"
#include "clauddey_serial.h"

#include <furi.h>
#include <stdio.h>
#include <string.h>
#include <gui/gui.h>
#include <gui/view_port.h>
#include <gui/canvas.h>
#include <gui/elements.h>
#include <input/input.h>
#include <notification/notification_messages.h>
#include <notification/notification.h>

#define TAG "Clauddey"

#define LOG_LINES 4
#define LOG_COLS 21

typedef enum {
    ClauddeyModeMonitor = 0,
    ClauddeyModeInteractive = 1,
} ClauddeyMode;

typedef enum {
    ClauddeyScreenMenu = 0,
    ClauddeyScreenSession = 1,
} ClauddeyScreen;

typedef struct {
    Gui* gui;
    ViewPort* view_port;
    FuriMessageQueue* events;
    FuriMutex* mutex;
    NotificationApp* notes;
    ClauddeySerial* serial;

    ClauddeyMode mode;
    ClauddeyScreen screen;
    bool running;
    bool host_connected;

    ClauddeyStatusMsg status;
    ClauddeyStatus last_feedback_status;
    ClauddeyAgent last_feedback_agent;

    char logs[LOG_LINES][LOG_COLS + 1];
    uint8_t log_count;
    uint8_t log_scroll; /* 0 = show newest */
} ClauddeyApp;

/* -------------------------------------------------------------------------- */
/*  Feedback (LED + vibro)                                                    */
/* -------------------------------------------------------------------------- */

/* Cursor identity: blue. Claude identity: magenta/purple. */
static const NotificationSequence seq_cursor_id = {
    &message_red_0,
    &message_green_0,
    &message_blue_255,
    &message_do_not_reset,
    NULL,
};

static const NotificationSequence seq_claude_id = {
    &message_red_255,
    &message_green_0,
    &message_blue_255,
    &message_do_not_reset,
    NULL,
};

static const NotificationSequence seq_task_done = {
    &message_display_backlight_on,
    &message_green_255,
    &message_vibro_on,
    &message_delay_500,
    &message_vibro_off,
    &message_delay_250,
    &message_green_0,
    NULL,
};

static const NotificationSequence seq_error = {
    &message_display_backlight_on,
    &message_red_255,
    &message_vibro_on,
    &message_delay_100,
    &message_vibro_off,
    &message_delay_50,
    &message_vibro_on,
    &message_delay_100,
    &message_vibro_off,
    &message_delay_50,
    &message_vibro_on,
    &message_delay_100,
    &message_vibro_off,
    NULL,
};

static const NotificationSequence seq_waiting = {
    &message_display_backlight_on,
    &message_vibro_on,
    &message_delay_50,
    &message_vibro_off,
    &message_delay_50,
    &message_vibro_on,
    &message_delay_50,
    &message_vibro_off,
    NULL,
};

static const NotificationSequence seq_thinking = {
    &message_vibro_on,
    &message_delay_50,
    &message_vibro_off,
    NULL,
};

static const NotificationSequence seq_reset_leds = {
    &message_red_0,
    &message_green_0,
    &message_blue_0,
    NULL,
};

static void clauddey_apply_agent_led(ClauddeyApp* app, ClauddeyAgent agent) {
    if(agent == ClauddeyAgentCursor) {
        notification_message(app->notes, &seq_cursor_id);
    } else if(agent == ClauddeyAgentClaude) {
        notification_message(app->notes, &seq_claude_id);
    } else {
        notification_message(app->notes, &seq_reset_leds);
    }
}

static void clauddey_apply_feedback(ClauddeyApp* app, const ClauddeyStatusMsg* msg) {
    /* Skip identical repeats so a chatty host does not buzz the motor forever. */
    if(msg->status == app->last_feedback_status && msg->agent == app->last_feedback_agent) {
        return;
    }
    app->last_feedback_status = msg->status;
    app->last_feedback_agent = msg->agent;

    notification_message(app->notes, &sequence_display_backlight_on);

    switch(msg->status) {
    case ClauddeyStatusDone:
        notification_message(app->notes, &seq_task_done);
        break;
    case ClauddeyStatusError:
        notification_message(app->notes, &seq_error);
        break;
    case ClauddeyStatusWaiting:
        notification_message(app->notes, &seq_waiting);
        clauddey_apply_agent_led(app, msg->agent);
        break;
    case ClauddeyStatusThinking:
    case ClauddeyStatusGenerating:
        notification_message(app->notes, &seq_thinking);
        clauddey_apply_agent_led(app, msg->agent);
        break;
    default:
        clauddey_apply_agent_led(app, msg->agent);
        break;
    }
}

/* -------------------------------------------------------------------------- */
/*  Local log ring (fixed buffers, no FuriString churn)                       */
/* -------------------------------------------------------------------------- */

static void clauddey_log_push(ClauddeyApp* app, const char* line) {
    if(app->log_count < LOG_LINES) {
        strncpy(app->logs[app->log_count], line, LOG_COLS);
        app->logs[app->log_count][LOG_COLS] = '\0';
        app->log_count++;
        return;
    }
    memmove(app->logs[0], app->logs[1], (LOG_LINES - 1) * (LOG_COLS + 1));
    strncpy(app->logs[LOG_LINES - 1], line, LOG_COLS);
    app->logs[LOG_LINES - 1][LOG_COLS] = '\0';
}

static void clauddey_log_status(ClauddeyApp* app, const ClauddeyStatusMsg* msg) {
    char line[LOG_COLS + 1];
    const char* who = (msg->agent == ClauddeyAgentCursor) ?
                          "CUR" :
                          (msg->agent == ClauddeyAgentClaude) ? "CLD" : "---";
    const char* body = msg->msg[0] ? msg->msg : clauddey_status_str(msg->status);
    snprintf(line, sizeof(line), "%s %s", who, body);
    clauddey_log_push(app, line);
    app->log_scroll = 0;
}

/* -------------------------------------------------------------------------- */
/*  Command gate — the only path that may talk to the host                    */
/* -------------------------------------------------------------------------- */

/**
 * HARD GATE.
 * Remote commands are legal only while ALL of these are true:
 *   1. We are on the session screen (not the mode menu)
 *   2. Operating mode is Interactive
 *   3. The host CDC port is open
 *
 * Monitor mode has no other TX call sites. Do not add any.
 */
static bool clauddey_commands_allowed(const ClauddeyApp* app) {
    return app->screen == ClauddeyScreenSession && app->mode == ClauddeyModeInteractive &&
           app->host_connected;
}

static void clauddey_try_send_command(ClauddeyApp* app, ClauddeyCmd cmd) {
    if(!clauddey_commands_allowed(app)) {
        FURI_LOG_D(
            TAG,
            "TX blocked cmd=%s mode=%u screen=%u link=%u",
            clauddey_cmd_str(cmd),
            (unsigned)app->mode,
            (unsigned)app->screen,
            (unsigned)app->host_connected);
        return;
    }

    char line[CLAUDDEY_TX_MAX];
    size_t n = clauddey_format_command(line, sizeof(line), cmd, app->status.agent);
    if(n == 0) return;

    if(clauddey_serial_tx(app->serial, line, n)) {
        FURI_LOG_I(TAG, "TX %s", line);
        clauddey_log_push(app, ">> cmd sent");
    }
}

/* -------------------------------------------------------------------------- */
/*  Drawing (GUI thread). Acquire mutex with a short timeout and skip frame.  */
/* -------------------------------------------------------------------------- */

static const char* clauddey_agent_label(ClauddeyAgent agent) {
    switch(agent) {
    case ClauddeyAgentCursor:
        return "CURSOR";
    case ClauddeyAgentClaude:
        return "CLAUDE";
    default:
        return "NO AGENT";
    }
}

static const char* clauddey_status_label(ClauddeyStatus status) {
    switch(status) {
    case ClauddeyStatusThinking:
        return "Thinking...";
    case ClauddeyStatusGenerating:
        return "Generating code...";
    case ClauddeyStatusWaiting:
        return "Waiting for approval";
    case ClauddeyStatusDone:
        return "Task complete";
    case ClauddeyStatusError:
        return "Error";
    default:
        return "Idle";
    }
}

static void clauddey_draw_menu(Canvas* canvas, ClauddeyApp* app) {
    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str_aligned(canvas, 64, 10, AlignCenter, AlignBottom, "Clauddey");

    canvas_set_font(canvas, FontSecondary);
    canvas_draw_str_aligned(canvas, 64, 22, AlignCenter, AlignBottom, "AI companion remote");

    const bool interactive = (app->mode == ClauddeyModeInteractive);
    canvas_draw_rframe(canvas, 18, 26, 92, 16, 3);
    if(interactive) {
        canvas_draw_rbox(canvas, 64, 27, 45, 14, 3);
        canvas_set_color(canvas, ColorWhite);
        canvas_draw_str_aligned(canvas, 86, 37, AlignCenter, AlignBottom, "INTERACT");
        canvas_set_color(canvas, ColorBlack);
        canvas_draw_str_aligned(canvas, 40, 37, AlignCenter, AlignBottom, "MONITOR");
    } else {
        canvas_draw_rbox(canvas, 19, 27, 45, 14, 3);
        canvas_set_color(canvas, ColorWhite);
        canvas_draw_str_aligned(canvas, 41, 37, AlignCenter, AlignBottom, "MONITOR");
        canvas_set_color(canvas, ColorBlack);
        canvas_draw_str_aligned(canvas, 86, 37, AlignCenter, AlignBottom, "INTERACT");
    }

    canvas_draw_str_aligned(
        canvas,
        64,
        50,
        AlignCenter,
        AlignBottom,
        app->host_connected ? "Host linked" : "Host offline");

    elements_button_left(canvas, "Mode");
    elements_button_center(canvas, "Start");
    elements_button_right(canvas, "Mode");
}

static void clauddey_draw_fit(Canvas* canvas, uint8_t x, uint8_t y, const char* text, uint8_t max_w) {
    char buf[48];
    strncpy(buf, text, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';
    while(buf[0] && canvas_string_width(canvas, buf) > max_w) {
        size_t n = strlen(buf);
        if(n <= 1) break;
        buf[n - 1] = '\0';
    }
    canvas_draw_str(canvas, x, y, buf);
}

static void clauddey_draw_session(Canvas* canvas, ClauddeyApp* app) {
    const bool interactive = (app->mode == ClauddeyModeInteractive);

    canvas_draw_box(canvas, 0, 0, 128, 12);
    canvas_set_color(canvas, ColorWhite);
    canvas_set_font(canvas, FontSecondary);
    canvas_draw_str(canvas, 2, 10, clauddey_agent_label(app->status.agent));
    canvas_draw_str_aligned(
        canvas, 126, 10, AlignRight, AlignBottom, interactive ? "INT" : "MON");
    canvas_set_color(canvas, ColorBlack);

    canvas_set_font(canvas, FontPrimary);
    const char* headline = app->status.msg[0] ? app->status.msg :
                                                clauddey_status_label(app->status.status);
    clauddey_draw_fit(canvas, 2, 24, headline, 124);

    canvas_set_font(canvas, FontSecondary);
    canvas_draw_line(canvas, 0, 27, 127, 27);

    /* Newest log at the bottom of the window; scroll moves the window up.
     * Interactive mode draws button hints on the last row, so show one fewer line. */
    uint8_t shown = app->log_count;
    uint8_t max_shown = interactive ? 2 : 3;
    if(shown > max_shown) shown = max_shown;
    int start = (int)app->log_count - (int)shown - (int)app->log_scroll;
    if(start < 0) start = 0;
    for(uint8_t i = 0; i < shown; i++) {
        uint8_t idx = (uint8_t)start + i;
        if(idx >= app->log_count) break;
        canvas_draw_str(canvas, 2, (uint8_t)(38 + i * 8), app->logs[idx]);
    }

    if(interactive) {
        elements_button_left(canvas, "Esc");
        elements_button_center(canvas, "OK");
        elements_button_right(canvas, "Act");
    } else {
        canvas_draw_str_aligned(canvas, 64, 63, AlignCenter, AlignBottom, "Back=menu  U/D=log");
    }
}

static void clauddey_draw_callback(Canvas* canvas, void* context) {
    ClauddeyApp* app = context;
    if(furi_mutex_acquire(app->mutex, 25) != FuriStatusOk) return;

    canvas_clear(canvas);
    if(app->screen == ClauddeyScreenMenu) {
        clauddey_draw_menu(canvas, app);
    } else {
        clauddey_draw_session(canvas, app);
    }

    furi_mutex_release(app->mutex);
}

/* -------------------------------------------------------------------------- */
/*  Input: queue only. Never TX from the GUI input callback.                  */
/* -------------------------------------------------------------------------- */

static void clauddey_input_callback(InputEvent* event, void* context) {
    ClauddeyApp* app = context;
    ClauddeyEvent ev = {.type = ClauddeyEventTypeInput, .input = *event};
    furi_message_queue_put(app->events, &ev, 0);
}

static void clauddey_handle_menu_input(ClauddeyApp* app, const InputEvent* ev) {
    if(ev->type != InputTypeShort && ev->type != InputTypeLong) return;

    if(ev->key == InputKeyBack) {
        app->running = false;
        return;
    }
    if(ev->type != InputTypeShort) return;

    if(ev->key == InputKeyLeft || ev->key == InputKeyRight) {
        app->mode = (app->mode == ClauddeyModeMonitor) ? ClauddeyModeInteractive :
                                                         ClauddeyModeMonitor;
        FURI_LOG_I(TAG, "mode=%s", app->mode == ClauddeyModeInteractive ? "INT" : "MON");
    } else if(ev->key == InputKeyOk) {
        app->screen = ClauddeyScreenSession;
        clauddey_log_push(
            app, app->mode == ClauddeyModeInteractive ? "interactive on" : "monitor only");
    }
}

static void clauddey_handle_session_input(ClauddeyApp* app, const InputEvent* ev) {
    /* Back is always local — never a host command. */
    if((ev->type == InputTypeShort || ev->type == InputTypeLong) && ev->key == InputKeyBack) {
        app->screen = ClauddeyScreenMenu;
        return;
    }

    /*
     * Monitor latch: visuals/haptics stay live, but D-Pad/OK cannot reach TX.
     * Up/Down only scroll the local log.
     */
    if(app->mode != ClauddeyModeInteractive) {
        if(ev->type == InputTypeShort || ev->type == InputTypeRepeat) {
            if(ev->key == InputKeyUp && app->log_scroll + 1 < app->log_count) {
                app->log_scroll++;
            } else if(ev->key == InputKeyDown && app->log_scroll > 0) {
                app->log_scroll--;
            }
        }
        return;
    }

    /* Interactive: D-Pad and OK are remote macros. The TX gate still checks
     * screen + mode + host link before any byte is written. */
    if(ev->type == InputTypeLong && ev->key == InputKeyUp) {
        clauddey_try_send_command(app, ClauddeyCmdDictate);
        return;
    }

    if(ev->type != InputTypeShort) return;

    switch(ev->key) {
    case InputKeyOk:
        clauddey_try_send_command(app, ClauddeyCmdOk);
        break;
    case InputKeyLeft:
        clauddey_try_send_command(app, ClauddeyCmdCancel);
        break;
    case InputKeyRight:
        clauddey_try_send_command(app, ClauddeyCmdRight);
        break;
    case InputKeyUp:
        clauddey_try_send_command(app, ClauddeyCmdUp);
        break;
    case InputKeyDown:
        clauddey_try_send_command(app, ClauddeyCmdDown);
        break;
    default:
        break;
    }
}

static void clauddey_handle_input(ClauddeyApp* app, const InputEvent* ev) {
    if(app->screen == ClauddeyScreenMenu) {
        clauddey_handle_menu_input(app, ev);
    } else {
        clauddey_handle_session_input(app, ev);
    }
}

/* -------------------------------------------------------------------------- */
/*  App lifecycle                                                             */
/* -------------------------------------------------------------------------- */

static ClauddeyApp* clauddey_app_alloc(void) {
    ClauddeyApp* app = malloc(sizeof(ClauddeyApp));
    app->mode = ClauddeyModeMonitor;
    app->screen = ClauddeyScreenMenu;
    app->running = true;
    app->host_connected = false;
    memset(&app->status, 0, sizeof(app->status));
    app->last_feedback_status = ClauddeyStatusIdle;
    app->last_feedback_agent = ClauddeyAgentNone;
    memset(app->logs, 0, sizeof(app->logs));
    app->log_count = 0;
    app->log_scroll = 0;

    app->mutex = furi_mutex_alloc(FuriMutexTypeNormal);
    app->events = furi_message_queue_alloc(16, sizeof(ClauddeyEvent));
    app->serial = clauddey_serial_alloc(app->events);

    app->view_port = view_port_alloc();
    view_port_draw_callback_set(app->view_port, clauddey_draw_callback, app);
    view_port_input_callback_set(app->view_port, clauddey_input_callback, app);

    app->gui = furi_record_open(RECORD_GUI);
    gui_add_view_port(app->gui, app->view_port, GuiLayerFullscreen);

    app->notes = furi_record_open(RECORD_NOTIFICATION);
    return app;
}

static void clauddey_app_free(ClauddeyApp* app) {
    notification_message(app->notes, &seq_reset_leds);
    gui_remove_view_port(app->gui, app->view_port);
    view_port_free(app->view_port);
    furi_record_close(RECORD_GUI);
    furi_record_close(RECORD_NOTIFICATION);
    clauddey_serial_free(app->serial);
    furi_message_queue_free(app->events);
    furi_mutex_free(app->mutex);
    free(app);
}

int32_t clauddey_app(void* p) {
    UNUSED(p);
    ClauddeyApp* app = clauddey_app_alloc();
    clauddey_serial_start(app->serial);
    FURI_LOG_I(TAG, "started");

    ClauddeyEvent event;
    while(app->running) {
        /* 100 ms poll keeps Back/redraw snappy if the queue is quiet. */
        FuriStatus st = furi_message_queue_get(app->events, &event, 100);
        if(st != FuriStatusOk) continue;

        furi_mutex_acquire(app->mutex, FuriWaitForever);

        switch(event.type) {
        case ClauddeyEventTypeInput:
            clauddey_handle_input(app, &event.input);
            break;
        case ClauddeyEventTypeStatus:
            app->status = event.status;
            clauddey_log_status(app, &event.status);
            clauddey_apply_feedback(app, &event.status);
            break;
        case ClauddeyEventTypeLink:
            app->host_connected = event.connected;
            if(event.connected) {
                clauddey_log_push(app, "host linked");
            } else {
                clauddey_log_push(app, "host gone");
            }
            break;
        default:
            break;
        }

        furi_mutex_release(app->mutex);
        view_port_update(app->view_port);
    }

    clauddey_serial_stop(app->serial);
    clauddey_app_free(app);
    return 0;
}
