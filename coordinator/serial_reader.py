# serial_reader.py
# Runs a background thread that reads from the USB serial bridge,
# parses packets, and updates the NodeRegistry.
#
# Framing strategy: scan for magic byte 0xAC, then read expected length
# based on the cmd byte. Discard bytes that don't match.

from __future__ import annotations

import serial
import threading
import logging
import time

import packet as pkt
from node_registry import NodeRegistry

log = logging.getLogger(__name__)

class SerialReader:
    def __init__(self, port: str, baud: int, registry: NodeRegistry):
        self._port     = port
        self._baud     = baud
        self._registry = registry
        self._ser: serial.Serial | None = None
        self._thread   = threading.Thread(target=self._run, daemon=True)
        self._running  = False
        self._send_lock = threading.Lock()

    def start(self):
        self._running = True
        self._thread.start()
        log.info(f"Serial reader started on {self._port} @ {self._baud}")

    def stop(self):
        self._running = False

    def send(self, data: bytes):
        """Thread-safe write to serial port."""
        if self._ser and self._ser.is_open:
            with self._send_lock:
                self._ser.write(data)
        else:
            log.warning("send() called but serial port not open")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _connect(self):
        while self._running:
            try:
                self._ser = serial.Serial(self._port, self._baud, timeout=1.0)
                log.info(f"Serial port {self._port} opened")
                return
            except serial.SerialException as e:
                log.warning(f"Cannot open {self._port}: {e}  — retrying in 3s")
                time.sleep(3)

    def _run(self):
        self._connect()
        buf = bytearray()

        while self._running and self._ser:
            try:
                chunk = self._ser.read(64)
                if not chunk:
                    continue
                buf.extend(chunk)
                buf = self._process_buffer(buf)

            except serial.SerialException as e:
                log.error(f"Serial error: {e} — reconnecting")
                time.sleep(1)
                self._connect()
                buf = bytearray()

    def _log_extraneous(self, data: bytearray):
        clean_line = data.decode('ascii', errors='backslashreplace').strip()
        if clean_line:
            print(f"Extraneous: {clean_line}", flush=True)

    def _process_buffer(self, buf: bytearray) -> bytearray:
        """
        Scan buf for valid packets, consuming bytes as we go.
        Returns the unconsumed remainder.
        """
        while len(buf) > 0:
            # 1. If we find a start byte at the beginning, try to parse a packet
            if buf[0] == pkt.STARTBYTE:
                if len(buf) < pkt.PKT_OVERHEAD:
                    break  # Wait for more data
                try:
                    if (decoded := pkt.Packet.from_bytes(buf)) is not None:
                        self.handle_pkt(decoded)
                        buf = buf[decoded.read_from_buf : ] #remove from incoming buffer
                        print(f"decoded len({decoded.read_from_buf}) (now {len(buf)} -> {decoded}")
                        continue
                    else: break #no pkt or exception? partial read
                except ValueError as e:
                    print(f"SerialReader {e}")
                # If length is invalid or decode failed, treat this byte as extraneous
                # and fall through to the scanning logic below.
            # 2. Scan for the next "event" (Start byte, Newline, or Buffer too big)
            # We treat everything until that point as extraneous text.
            idx = 1
            while idx < len(buf):
                if buf[idx] == pkt.STARTBYTE or buf[idx] == ord('\n') or idx > 256:
                    break
                idx += 1
            skipped = buf[:idx]
            buf = buf[idx:]
            self._log_extraneous(skipped)
        return buf

    def handle_pkt(self, pkt: pkt.Packet):
        self._registry.update(pkt)
