/**
 * @file clauddey_serial.h
 * @brief USB CDC worker: host JSON in, command JSON out.
 *
 * CDC callbacks run in USB interrupt context. They only set thread flags.
 * Parsing and GUI updates happen on the worker / app threads.
 */
#pragma once

#include "clauddey_protocol.h"

#include <furi.h>
#include <input/input.h>

#ifdef __cplusplus
extern "C" {
#endif

/** CDC interface 1 = second VCP (CLI stays on 0 when dual-CDC is active). */
#define CLAUDDEY_CDC_IF 1

typedef enum {
    ClauddeyEventTypeInput = 0,
    ClauddeyEventTypeStatus,
    ClauddeyEventTypeLink,
} ClauddeyEventType;

typedef struct {
    ClauddeyEventType type;
    InputEvent input;
    ClauddeyStatusMsg status;
    bool connected;
} ClauddeyEvent;

typedef struct ClauddeySerial ClauddeySerial;

ClauddeySerial* clauddey_serial_alloc(FuriMessageQueue* events);
void clauddey_serial_free(ClauddeySerial* serial);

void clauddey_serial_start(ClauddeySerial* serial);
void clauddey_serial_stop(ClauddeySerial* serial);

bool clauddey_serial_is_connected(ClauddeySerial* serial);

/**
 * Transmit one already-formatted command line.
 * Callers MUST go through the Interactive-mode gate in clauddey.c.
 */
bool clauddey_serial_tx(ClauddeySerial* serial, const char* line, size_t len);

#ifdef __cplusplus
}
#endif
