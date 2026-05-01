# packet.py - TTeacher wire protocol (keep in sync with Packet.h)
# Frame: [startbyte:1][id:1][type:1][plen:1][payload:N][checksum:1]

from __future__ import annotations

import struct, typing, enum
from dataclasses import dataclass, asdict

# --- Constants ---
STARTBYTE = 0xAC
PKT_HEADER_FMT = '<BHHBB' #start-u8, from-u16, to-u16, type-u8, len-u8
PKT_PYLD_OFFSET = struct.calcsize(PKT_HEADER_FMT)
PKT_OVERHEAD = PKT_PYLD_OFFSET + 1   # checksum
PAYLOAD_MAX = 245
COORDINATOR_ID = 0xFE

# --- Enums ---
class Cmd(enum.IntEnum):
    Ping      = 0x00
    Error     = 0x01
    Version   = 0x02
    DebugMsg  = 0x03
    UpdateInit= 0x11
    UpdateData= 0x12
    IMU_DATA  = 0xA1
    SET_STATE = 0xA2
    ZERO      = 0xA3

class LedMode(enum.IntEnum):
    OFF = 0
    Solid = 1
    Beat = 2
    Spotlight = 3

# --- Payload Classes ---

@dataclass
class StrPayload:
    value: str = ""
    TYPE = Cmd.Version
    @staticmethod
    def from_bytes(data: bytes) -> 'StrPayload': return StrPayload(data.decode('ascii', errors='replace'))
    def to_bytes(self) -> bytes: return self.value.encode('ascii')
    def __str__(self) -> str: return self.value

@dataclass
class UpdateInit:
    total_chunks: int
    full_update_chksum: int
    total_size: int

    TYPE = Cmd.UpdateInit
    PACK_FMT = '<HHQ'
    SIZE = struct.calcsize(PACK_FMT)
    @staticmethod
    def from_bytes(data: bytes) -> 'UpdateInit':
        t, f, s = struct.unpack(UpdateInit.PACK_FMT, data[:UpdateInit.SIZE])
        return UpdateInit(t, f, s)
    def to_bytes(self) -> bytes: return struct.pack(UpdateInit.PACK_FMT, self.total_chunks, self.full_update_chksum, self.total_size)
    def __str__(self) -> str: return str(asdict(self))

@dataclass
class UpdateData:
    sequence: int
    full_update_chksum: int
    data: bytes

    TYPE = Cmd.UpdateData
    PACK_FMT = '<HH'
    SIZE = struct.calcsize(PACK_FMT)
    @staticmethod
    def from_bytes(data: bytes) -> 'UpdateData':
        s, c = struct.unpack(UpdateInit.PACK_FMT, data[:UpdateData.SIZE])
        return UpdateData(s, c, data[UpdateData.SIZE:])
    def to_bytes(self) -> bytes: return struct.pack(self.PACK_FMT, self.sequence, self.full_update_chksum) + self.data
    def __str__(self) -> str: return str(asdict(self))

@dataclass
class UnknownPayload:
    """Unknown type: raw bytes"""
    cmd: int
    data: bytes
    @property
    def size(self) -> int: return len(self.data)
    def to_bytes(self) -> bytes: return self.data
    def __str__(self) -> str: return f"raw={self.data.hex()}"

@dataclass
class ImuPayload:
    """IMU data: seq(2) + pitch(4) + roll(4) = 14 bytes"""
    seq: int
    pitch: float
    roll: float

    TYPE = Cmd.IMU_DATA
    PACK_FMT = '<Hff'
    SIZE = struct.calcsize(PACK_FMT)

    def to_bytes(self) -> bytes:
        return struct.pack(self.PACK_FMT, self.seq, self.pitch, self.roll)
    @staticmethod
    def from_bytes(data: bytes) -> 'ImuPayload':
        return ImuPayload(*struct.unpack(ImuPayload.PACK_FMT, data[:ImuPayload.SIZE]))
    def __str__(self) -> str:
        return f"seq={self.seq}, pitch={self.pitch:+7.2f}, roll={self.roll:+7.2f}"

@dataclass
class SetStatePayload:
    """Set state: led_mode(1) + color(4) + param1(4) + param2(4) = 15 bytes"""
    led_mode: LedMode
    color: int = 0
    param1: int = 0
    param2: int = 0

    TYPE = Cmd.SET_STATE
    PACK_FMT = '<BIII'
    SIZE = struct.calcsize(PACK_FMT)

    def to_bytes(self) -> bytes:
        return struct.pack(self.PACK_FMT, self.led_mode.value, self.color, self.param1, self.param2)
    @staticmethod
    def from_bytes(data: bytes) -> 'SetStatePayload':
        led_mode, color, param1, param2 = struct.unpack(SetStatePayload.PACK_FMT, data[:15])
        return SetStatePayload(LedMode(led_mode), color, param1, param2)
    def __str__(self) -> str: return str(asdict(self))

# --- Payload Registry ---
_PAYLOADS = {
    Cmd.Version: StrPayload,
    Cmd.Error:   StrPayload,
    Cmd.DebugMsg:   StrPayload,
    Cmd.UpdateInit: UpdateInit,
    Cmd.UpdateData: UpdateData,
    Cmd.IMU_DATA: ImuPayload,
    Cmd.SET_STATE: SetStatePayload,
}

# --- Main Packet Class ---
@dataclass
class Packet:
    """Complete TTeacher protocol packet"""
    from_id: int = COORDINATOR_ID
    to_id: int = 0
    type: Cmd = Cmd.Ping
    payload: None | typing.Union[ImuPayload, SetStatePayload, StrPayload, UnknownPayload] = None
    read_from_buf: int = 0

    def __post_init__(self):
        if isinstance(self.type, int):
            self.type = Cmd(self.type)

    @property
    def plen(self) -> int:
        return getattr(self.payload, 'SIZE', len(self.payload.to_bytes()) if self.payload else 0)

    def to_bytes(self) -> bytes:
        payload_bytes = self.payload.to_bytes() if self.payload else b''
        header = struct.pack('<BHHBB', STARTBYTE, self.from_id, self.to_id, self.type & 0xFF, len(payload_bytes) & 0xFF)
        return header + payload_bytes + bytes([Packet._checksum(header + payload_bytes)])

    @classmethod
    def from_bytes(cls, raw: bytes) -> typing.Optional['Packet']:
        """Deserializes a packet. Returns None if incomplete, raises exception if invalid."""
        if raw[0] != STARTBYTE: raise ValueError("wrong start byte")
        if len(raw) < PKT_PYLD_OFFSET:
            return None #unfinished buffer
        _, from_id, to_id, pkt_type, plen = struct.unpack(PKT_HEADER_FMT, raw[:PKT_PYLD_OFFSET])
        total = PKT_OVERHEAD + plen
        if len(raw) < total:
            return None #unfinished buffer
        if (calced := Packet._checksum(raw[:total-1])) != raw[total-1]:
            raise ValueError(f"Checksum mismatch: expected {raw[total-1]:02x}, got {calced:02x}")
        payload_data = raw[PKT_PYLD_OFFSET : PKT_PYLD_OFFSET + plen]
        try:
            cmd = Cmd(pkt_type)
            payload_cls = _PAYLOADS.get(cmd)
            if payload_cls:
                payload = payload_cls.from_bytes(payload_data)
            else:
                payload = UnknownPayload(pkt_type, payload_data)
        except Exception as e:
            print(f"Packet decode error: {e}")
            payload, cmd = UnknownPayload(pkt_type, payload_data), Cmd.PING
        return cls(from_id=from_id, to_id=to_id, type=cmd, payload=payload, read_from_buf=total)

    @staticmethod
    def _checksum(data: bytes, startval: int = 0) -> int:
        # CRC-8, polynomial 0x07 (x^8 + x^2 + x^1 + 1)
        crc = startval & 0xFF
        for byte in data:
            crc ^= (byte & 0xFF)
            for _ in range(8):
                crc = (((crc << 1) ^ 0x07) if (crc & 0x80) else (crc << 1)) & 0xFF
        return crc & 0xFF

    # --- Factory methods ---
    @classmethod
    def imu_data(cls, to_id: int, seq: int, pitch: float, roll: float) -> 'Packet':
        return cls(to_id=to_id, type=Cmd.IMU_DATA, payload=ImuPayload(seq, pitch, roll))

    @classmethod
    def set_state(cls, to_id: int, led_mode: LedMode, color: int = 0, p1=0, p2=0) -> 'Packet':
        return cls(to_id=to_id, type=Cmd.SET_STATE, payload=SetStatePayload(led_mode, color, p1, p2))

    def __str__(self) -> str:
        return f"Packet(from=0x{self.from_id:04X}, to=0x{self.to_id:04X}, {self.type.name} {self.payload})"
