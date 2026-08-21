/**
 * @file clauddey_serial.c
 * @brief Non-blocking USB CDC bring-up on interface 1.
 *
 * Pattern matches the official USB-UART bridge:
 *   - ISR callback sets a thread flag
 *   - worker thread reads CDC into a line buffer
 *   - complete lines are parsed and posted to the GUI queue (0 timeout)
 */
#include "clauddey_serial.h"

#include <furi_hal.h>
#include <furi_hal_usb.h>
#include <furi_hal_usb_cdc.h>

#define TAG "ClauddeySerial"

#define WORKER_STACK 1024
#define RX_ACCUM_MAX CLAUDDEY_LINE_MAX

typedef enum {
    WorkerEvtStop = (1 << 0),
    WorkerEvtCdcRx = (1 << 1),
    WorkerEvtLink = (1 << 2),
} WorkerEvt;

struct ClauddeySerial {
    FuriThread* thread;
    FuriMessageQueue* events;
    FuriMutex* mutex;
    FuriHalUsbInterface* usb_if_prev;
    volatile bool running;
    volatile bool connected;
    char accum[RX_ACCUM_MAX];
    size_t accum_len;
};

static void clauddey_post_link(ClauddeySerial* s, bool connected) {
    ClauddeyEvent ev = {
        .type = ClauddeyEventTypeLink,
        .connected = connected,
    };
    /* Drop if the GUI is busy — a later packet will refresh the badge. */
    furi_message_queue_put(s->events, &ev, 0);
}

static void clauddey_cdc_tx_complete(void* context) {
    UNUSED(context);
}

static void clauddey_cdc_rx(void* context) {
    ClauddeySerial* s = context;
    if(s->thread) {
        furi_thread_flags_set(furi_thread_get_id(s->thread), WorkerEvtCdcRx);
    }
}

static void clauddey_cdc_state(void* context, CdcState state) {
    ClauddeySerial* s = context;
    bool connected = (state == CdcStateConnected);
    s->connected = connected;
    if(s->thread) {
        furi_thread_flags_set(furi_thread_get_id(s->thread), WorkerEvtLink);
    }
}

static void clauddey_cdc_ctrl(void* context, CdcCtrlLine lines) {
    ClauddeySerial* s = context;
    /* DTR is a better "host opened the port" signal than bus state alone. */
    bool connected = (lines & CdcCtrlLineDTR) != 0;
    s->connected = connected;
    if(s->thread) {
        furi_thread_flags_set(furi_thread_get_id(s->thread), WorkerEvtLink);
    }
}

static void clauddey_cdc_config(void* context, struct usb_cdc_line_coding* config) {
    UNUSED(context);
    UNUSED(config);
}

static CdcCallbacks clauddey_cdc_cb = {
    .tx_ep_callback = clauddey_cdc_tx_complete,
    .rx_ep_callback = clauddey_cdc_rx,
    .state_callback = clauddey_cdc_state,
    .ctrl_line_callback = clauddey_cdc_ctrl,
    .config_callback = clauddey_cdc_config,
};

static void clauddey_feed_bytes(ClauddeySerial* s, const uint8_t* data, size_t len) {
    for(size_t i = 0; i < len; i++) {
        char c = (char)data[i];
        if(c == '\r') continue;

        if(c == '\n') {
            if(s->accum_len > 0) {
                s->accum[s->accum_len] = '\0';
                ClauddeyEvent ev = {.type = ClauddeyEventTypeStatus};
                if(clauddey_parse_status(s->accum, &ev.status)) {
                    furi_message_queue_put(s->events, &ev, 0);
                } else {
                    FURI_LOG_D(TAG, "drop bad json (%u B)", (unsigned)s->accum_len);
                }
            }
            s->accum_len = 0;
            continue;
        }

        if(s->accum_len + 1 >= sizeof(s->accum)) {
            /* Overflow: discard until the next newline so we resync. */
            s->accum_len = 0;
            continue;
        }
        s->accum[s->accum_len++] = c;
    }
}

static int32_t clauddey_serial_worker(void* context) {
    ClauddeySerial* s = context;
    uint8_t pkt[CDC_DATA_SZ];

    s->usb_if_prev = furi_hal_usb_get_config();
    furi_hal_usb_unlock();
    if(!furi_hal_usb_set_config(&usb_cdc_dual, NULL)) {
        FURI_LOG_E(TAG, "usb_cdc_dual failed");
        return -1;
    }
    furi_hal_cdc_set_callbacks(CLAUDDEY_CDC_IF, &clauddey_cdc_cb, s);
    FURI_LOG_I(TAG, "CDC%u up", (unsigned)CLAUDDEY_CDC_IF);

    while(s->running) {
        uint32_t flags = furi_thread_flags_wait(
            WorkerEvtStop | WorkerEvtCdcRx | WorkerEvtLink, FuriFlagWaitAny, 100);

        /* Timeouts and other wait errors come back with FuriFlagError set.
         * FuriFlagErrorTimeout is not a single bit — compare, do not AND. */
        if(flags & FuriFlagError) {
            continue;
        }

        if(flags & WorkerEvtStop) break;

        if(flags & WorkerEvtLink) {
            clauddey_post_link(s, s->connected);
        }

        if(flags & WorkerEvtCdcRx) {
            if(furi_mutex_acquire(s->mutex, 50) != FuriStatusOk) continue;
            /* Flags coalesce: drain every pending 64-byte packet. */
            while(true) {
                int32_t n = furi_hal_cdc_receive(CLAUDDEY_CDC_IF, pkt, sizeof(pkt));
                if(n <= 0) break;
                clauddey_feed_bytes(s, pkt, (size_t)n);
            }
            furi_mutex_release(s->mutex);
        }
    }

    furi_hal_cdc_set_callbacks(CLAUDDEY_CDC_IF, NULL, NULL);
    furi_hal_usb_unlock();
    if(s->usb_if_prev) {
        furi_hal_usb_set_config(s->usb_if_prev, NULL);
    }
    FURI_LOG_I(TAG, "CDC stopped");
    return 0;
}

ClauddeySerial* clauddey_serial_alloc(FuriMessageQueue* events) {
    furi_assert(events);
    ClauddeySerial* s = malloc(sizeof(ClauddeySerial));
    s->events = events;
    s->mutex = furi_mutex_alloc(FuriMutexTypeNormal);
    s->thread = NULL;
    s->usb_if_prev = NULL;
    s->running = false;
    s->connected = false;
    s->accum_len = 0;
    return s;
}

void clauddey_serial_free(ClauddeySerial* serial) {
    if(!serial) return;
    clauddey_serial_stop(serial);
    furi_mutex_free(serial->mutex);
    free(serial);
}

void clauddey_serial_start(ClauddeySerial* serial) {
    furi_assert(serial);
    if(serial->thread) return;
    serial->running = true;
    serial->thread =
        furi_thread_alloc_ex("ClauddeyCDC", WORKER_STACK, clauddey_serial_worker, serial);
    furi_thread_start(serial->thread);
}

void clauddey_serial_stop(ClauddeySerial* serial) {
    furi_assert(serial);
    if(!serial->thread) return;
    serial->running = false;
    furi_thread_flags_set(furi_thread_get_id(serial->thread), WorkerEvtStop);
    furi_thread_join(serial->thread);
    furi_thread_free(serial->thread);
    serial->thread = NULL;
}

bool clauddey_serial_is_connected(ClauddeySerial* serial) {
    return serial && serial->connected;
}

bool clauddey_serial_tx(ClauddeySerial* serial, const char* line, size_t len) {
    if(!serial || !line || len == 0) return false;
    if(!serial->connected) return false;
    if(len > CDC_DATA_SZ) {
        /* v1 commands fit in one 64-byte packet; refuse anything larger. */
        FURI_LOG_W(TAG, "tx too long (%u)", (unsigned)len);
        return false;
    }

    if(furi_mutex_acquire(serial->mutex, 50) != FuriStatusOk) return false;
    /* furi_hal_cdc_send copies internally; the const cast is API-safe. */
    furi_hal_cdc_send(CLAUDDEY_CDC_IF, (uint8_t*)line, (uint16_t)len);
    furi_mutex_release(serial->mutex);
    return true;
}
