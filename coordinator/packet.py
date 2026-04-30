# packet.py - TTeacher wire protocol (keep in sync with Packet.h)
# Frame: [startbyte:1][id:1][type:1][plen:1][payload:N][checksum:1]

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Union

# --- Constants ---
STARTBYTE = 0xAC
PKT_OVERHEAD = 5
PAYLOAD_MAX = 245
COORDINATOR_ID = 0xFE

# --- Enums ---
class Cmd(IntEnum):
    PING = 0x00
    VERSION = 0x01
    IMU_DATA = 0x02
    SET_STATE = 0x03

class LedMode(IntEnum):
    OFF = 0
    Solid = 1
    Beat = 2
    Spotlight = 3
# --- Payload Classes ---
@dataclass
class ImuPayload:
    """IMU data: node_id(2) + seq(2) + pitch(4) + roll(4) = 14 bytes"""
    node_id: int
    seq: int
    pitch: float
    roll: float

    SIZE = 14
    TYPE = Cmd.IMU_DATA
    PACK_FMT = '<HHff'

    def to_bytes(self) -> bytes:
        return struct.pack(self.PACK_FMT, self.node_id, self.seq, self.pitch, self.roll)
    @staticmethod
    def from_bytes(data: bytes) -> 'ImuPayload':
        return ImuPayload(*struct.unpack(ImuPayload.PACK_FMT, data[:14]))
    def __str__(self) -> str:
        return f"node=0x{self.node_id:02X}, seq={self.seq}, pitch={self.pitch:+7.2f}, roll={self.roll:+7.2f}"

@dataclass
class SetStatePayload:
    """Set state: node_id(2) + led_mode(1) + color(4) + param1(4) + param2(4) = 15 bytes"""
    node_id: int
    led_mode: LedMode
    color: int = 0
    param1: int = 0
    param2: int = 0

    SIZE = 15
    TYPE = Cmd.SET_STATE
    PACK_FMT = '<HBIII'

    def to_bytes(self) -> bytes:
        return struct.pack(self.PACK_FMT, self.node_id, self.led_mode.value, self.color, self.param1, self.param2)

    @staticmethod
    def from_bytes(data: bytes) -> 'SetStatePayload':
        node_id, led_mode, color, param1, param2 = struct.unpack(SetStatePayload.PACK_FMT, data[:15])
        return SetStatePayload(node_id, LedMode(led_mode), color, param1, param2)

    def __str__(self) -> str:
        return f"target=0x{self.node_id:02X}, mode={self.led_mode.name}, color=0x{self.color:06X}"

@dataclass
class PingPayload:
    """Ping: no data"""
    SIZE = 0
    TYPE = Cmd.PING
    def to_bytes(self) -> bytes: return b''
    def __str__(self) -> str: return ""

    @staticmethod
    def from_bytes(data: bytes) -> 'PingPayload': return PingPayload()

@dataclass
class VersionPayload:
    """Version: raw string payload"""
    version: str = ""
    TYPE = Cmd.VERSION
    def to_bytes(self) -> bytes: return self.version.encode('ascii')
    def __str__(self) -> str: return f"ver={self.version}"

    @staticmethod
    def from_bytes(data: bytes) -> 'VersionPayload': return VersionPayload(data.decode('ascii', errors='replace'))

@dataclass
class UnknownPayload:
    """Unknown type: raw bytes"""
    cmd: int
    data: bytes
    @property
    def size(self) -> int: return len(self.data)
    def to_bytes(self) -> bytes: return self.data
    def __str__(self) -> str: return f"raw={self.data.hex()}"

# --- Payload Registry ---
_PAYLOADS = {
    Cmd.PING: PingPayload,
    Cmd.VERSION: VersionPayload,
    Cmd.IMU_DATA: ImuPayload,
    Cmd.SET_STATE: SetStatePayload,
}

# --- Main Packet Class ---
@dataclass
class Packet:
    """Complete TTeacher protocol packet"""
    id: int = COORDINATOR_ID
    type: Cmd = Cmd.PING
    payload: None | Union[ImuPayload, SetStatePayload, PingPayload, VersionPayload, UnknownPayload] = None

    def __post_init__(self):
        if self.payload is None:
            self.payload = PingPayload()
        if isinstance(self.type, int):
            self.type = Cmd(self.type)

    @property
    def plen(self) -> int:
        return getattr(self.payload, 'SIZE', len(self.payload.to_bytes()) if self.payload else 0)

    def _checksum(self, data: bytes) -> int:
        cs = 0
        for b in data: cs ^= b
        return cs

    def to_bytes(self) -> bytes:
        payload_bytes = self.payload.to_bytes() if self.payload else b''
        header = bytes([STARTBYTE, self.id & 0xFF, self.type & 0xFF, len(payload_bytes) & 0xFF])
        return header + payload_bytes + bytes([self._checksum(header + payload_bytes)])

    @classmethod
    def from_bytes(cls, raw: bytes) -> Optional['Packet']:
        if len(raw) < PKT_OVERHEAD or raw[0] != STARTBYTE:
            return None
        pkt_id, pkt_type, plen = raw[1], raw[2], raw[3]
        total = PKT_OVERHEAD + plen
        if len(raw) < total or cls._xor_checksum(raw[:total-1]) != raw[total-1]:
            return None
        payload_data = raw[4:4+plen]
        try:
            cmd = Cmd(pkt_type)
            payload_cls = _PAYLOADS.get(cmd)
            if payload_cls:
                payload = payload_cls.from_bytes(payload_data)
            else:
                payload = UnknownPayload(pkt_type, payload_data)
        except:
            payload = UnknownPayload(pkt_type, payload_data)
        return cls(id=pkt_id, type=cmd, payload=payload)

    @staticmethod
    def _xor_checksum(data: bytes) -> int:
        cs = 0
        for b in data: cs ^= b
        return cs

    # --- Factory methods ---
    @classmethod
    def ping(cls, id) -> 'Packet':
        return cls(id=id, type=Cmd.PING, payload=PingPayload())

    @classmethod
    def imu_data(cls, node_id: int, seq: int, pitch: float, roll: float) -> 'Packet':
        return cls(id=node_id, type=Cmd.IMU_DATA, payload=ImuPayload(node_id, seq, pitch, roll))

    @classmethod
    def set_state(cls, node_id: int, led_mode: LedMode, color: int = 0, p1=0, p2=0, id=COORDINATOR_ID) -> 'Packet':
        return cls(id=id, type=Cmd.SET_STATE, payload=SetStatePayload(node_id, led_mode, color, p1, p2))

    def __str__(self) -> str:
        return f"Packet(id=0x{self.id:02X}, {self.type.name} {self.payload})"
