"""
Bluetooth BLE transport — uses bleak to talk to the Flipper's serial-over-BLE
GATT profile (the same simple `ble_profile_serial`-based service used by the
sibling flipper-claude-buddy project, not the heavier bonded NUS variant).

Connection flow:
  1. Scan for a BLE device advertising config.FLIPPER_ADV_UUID, falling back to
     a name-prefix match against config.BT_DEVICE_NAME ("Flipper").
  2. Connect and verify the serial TX/RX GATT characteristics exist.
  3. Subscribe to notifications on the TX characteristic (Flipper -> host).
  4. Incoming notifications are buffered; readline() returns complete lines.

Flipper BLE serial UUIDs:
  Adv UUID: 00003082-0000-1000-8000-00805f9b34fb  (advertised service, used for scan)
  TX char:  19ed82ae-ed21-4c9d-4145-228e61fe0000  (Flipper -> host, notify)
  RX char:  19ed82ae-ed21-4c9d-4145-228e62fe0000  (host -> Flipper, write)

Requires: pip install bleak
"""

from __future__ import annotations

import asyncio
import logging

import config
from transport import Transport

log = logging.getLogger(__name__)

FLIPPER_SERIAL_TX_UUID = "19ed82ae-ed21-4c9d-4145-228e61fe0000"  # Flipper->host (notify)
FLIPPER_SERIAL_RX_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"  # host->Flipper (write)


class BtTransport(Transport):
    def __init__(self) -> None:
        self._client = None
        self._tx_uuid = FLIPPER_SERIAL_TX_UUID
        self._rx_uuid = FLIPPER_SERIAL_RX_UUID
        self._rx_buf = bytearray()
        self._rx_event = asyncio.Event()
        self._closed = True

    async def connect(self) -> bool:
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError:
            log.error("BLE transport requires bleak: pip install bleak")
            return False

        adv_uuid = config.FLIPPER_ADV_UUID.lower()
        name_prefix = config.BT_DEVICE_NAME

        def _is_flipper(device, adv_data) -> bool:
            if adv_uuid in [u.lower() for u in adv_data.service_uuids]:
                return True
            return bool(name_prefix and device.name and device.name.startswith(name_prefix))

        log.info(
            "BLE: scanning for Flipper (UUID %s or name prefix %r, timeout %.0fs)...",
            config.FLIPPER_ADV_UUID, name_prefix, config.BT_SCAN_TIMEOUT,
        )
        device = await BleakScanner.find_device_by_filter(
            _is_flipper, timeout=config.BT_SCAN_TIMEOUT,
        )
        if device is None:
            log.warning("BLE: Flipper not found - is Bluetooth enabled and advertising?")
            return False

        log.info("BLE: found %s (%s)", device.name, device.address)
        self._client = BleakClient(device, disconnected_callback=self._on_disconnect)
        try:
            await self._client.connect()
        except Exception as exc:
            log.error("BLE: connect to %s failed: %s", device.name, exc)
            self._client = None
            return False

        try:
            tx_char = self._client.services.get_characteristic(self._tx_uuid)
            rx_char = self._client.services.get_characteristic(self._rx_uuid)
        except Exception:
            tx_char = rx_char = None
        if tx_char is None or rx_char is None:
            log.error(
                "BLE: serial characteristics not found on %s - "
                "is the Flipper running the Clauddey app?",
                device.name,
            )
            await self._client.disconnect()
            self._client = None
            return False

        mtu = getattr(self._client, "mtu_size", 23)
        log.info(
            "BLE: negotiated MTU=%d (write chunk=%d)",
            mtu, max(1, min(mtu - 3, config.BT_WRITE_CHUNK)),
        )

        await self._client.start_notify(self._tx_uuid, self._on_notify)
        self._closed = False
        self._rx_buf.clear()
        log.info("BLE: connected to %s", device.name)
        return True

    async def readline(self) -> bytes:
        """Block until a complete newline-terminated line arrives via BLE notify."""
        while True:
            if b"\n" in self._rx_buf:
                idx = self._rx_buf.index(b"\n")
                line = bytes(self._rx_buf[: idx + 1])
                del self._rx_buf[: idx + 1]
                return line
            if self._closed:
                return b""
            self._rx_event.clear()
            # Re-check after clear to avoid losing a notification that arrived
            # between the buffer check above and clearing the event.
            if b"\n" in self._rx_buf or self._closed:
                continue
            await self._rx_event.wait()

    async def write(self, data: bytes) -> None:
        """Write to the RX characteristic in MTU-safe chunks.

        Uses write-without-response so the ATT layer doesn't add a second ACK
        on top of Clauddey's own line protocol.
        """
        mtu = getattr(self._client, "mtu_size", 23)
        chunk = max(1, min(mtu - 3, config.BT_WRITE_CHUNK))
        for i in range(0, len(data), chunk):
            await self._client.write_gatt_char(
                self._rx_uuid, data[i : i + chunk], response=False,
            )

    async def drain(self) -> None:
        pass  # BLE writes are already awaited

    async def get_rssi(self) -> int | None:
        if not self._client or not self._client.is_connected:
            return None
        backend = getattr(self._client, "_backend", None)
        if backend is None or not hasattr(backend, "get_rssi"):
            return None
        try:
            return int(await backend.get_rssi())
        except Exception as exc:
            log.debug("BLE: RSSI read failed: %s", exc)
            return None

    def close(self) -> None:
        self._closed = True
        self._rx_event.set()  # unblock any waiting readline()
        if self._client:
            asyncio.ensure_future(self._client.disconnect())

    async def aclose(self) -> None:
        """Disconnect BLE and wait for the peer to see it.

        Without awaiting the GATT disconnect, the Flipper's BLE stack waits
        for the link-supervision timeout before it notices and resumes
        advertising, so a quick bridge restart can't reconnect right away.
        """
        self._closed = True
        self._rx_event.set()
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception as exc:
            log.warning("BLE: disconnect error: %s", exc)

    @property
    def is_closing(self) -> bool:
        if self._closed:
            return True
        return self._client is None or not self._client.is_connected

    # -- BLE callbacks --------------------------------------------------

    def _on_notify(self, _handle, data: bytearray) -> None:
        self._rx_buf.extend(data)
        self._rx_event.set()

    def _on_disconnect(self, _client) -> None:
        log.warning("BLE: disconnected")
        self._closed = True
        self._rx_event.set()
