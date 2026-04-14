#pragma once
// ============================================================
//  Packet.h  —  TTeacher wire protocol
//  No Arduino dependencies. Safe for native unit tests.
//
//  Frame layout:
//    [startbyte : 1]  0xAC (STARTBYTE)
//    [id        : 1]  Node ID or Version
//    [type      : 1]  Command Type (Cmd)
//    [plen      : 1]  payload byte count (0..PAYLOAD_MAX)
//    [payload   : N]
//    [chksum    : 1]  XOR of all preceding bytes
//
//  Total overhead: 5 bytes. Max frame: 5 + PAYLOAD_MAX bytes.
// ============================================================

#include <cstdint>
#include <cstring>
#include <functional>

namespace comms {

// ---- constants ----------------------------------------------------
static constexpr uint8_t  STARTBYTE    = 0xAC;
static constexpr uint8_t  PKT_OVERHEAD = 5;     // startbyte + id + plen + chksum
static constexpr uint8_t  FRAME_MAX    = 250;   //esp-now max payload is 250 bytes
static constexpr uint8_t  PAYLOAD_MAX  = FRAME_MAX - PKT_OVERHEAD;

struct __attribute__((__packed__)) PktHeader {
  uint8_t startbyte;
  uint8_t id;
  uint8_t type;
  uint8_t plen;
};

enum PktReadState {
  PktUnfinished = -1,
  PktInvalid    =  0,
  PktValid      =  1
};

// Helper for payload access
static constexpr uint8_t PAYLOAD_OFFSET = sizeof(PktHeader);

PktReadState isPacketValid(const uint8_t* pkt, const uint16_t len);
uint8_t checksum(const uint8_t* buf, uint16_t len, uint8_t startval = 0);

uint8_t pktSerialize(uint8_t id, uint8_t type, const uint8_t* payload, const uint8_t payloadLen, uint8_t* buf, uint16_t buflen);

// defines function to write data (like Serial.write)
using PktSendFunc = std::function<void(const uint8_t* data, uint8_t len)>;
void pktSend(const PktHeader& hdr, const uint8_t* payload, uint8_t plen, PktSendFunc sendFunc);


// ============================================================
//  Payload types / structs
// ============================================================

// ---- command IDs (low byte of id field) ---------------------------
enum Cmd : uint8_t {
    CMD_PING      = 0x00,   // coord -> broadcast (or relay alive ping)
    CMD_VERSION   = 0x01,   // get or reply with program version
    CMD_IMU_DATA  = 0x02,   // node  -> coordinator
    CMD_SET_STATE = 0x03,   // coord -> node
};

// ---- LED mode values (used in CMD_SET_STATE payload) --------------
enum LedMode : uint8_t {
    LED_IMU   = 0x00,
    LED_SOLID = 0x01,
    LED_FLASH = 0x02,
    LED_CHASE = 0x03,
    LED_OFF   = 0xFF,
};


#pragma pack(push, 1)
struct __attribute__((__packed__)) ImuPayload {
    uint16_t node_id;
    uint16_t seq;
    int16_t  ax, ay, az;
    int16_t  gx, gy;
};
static constexpr uint8_t ImuPayloadSize = sizeof(ImuPayload);

struct __attribute__((__packed__)) SetStatePayload {
    uint16_t node_id;
    uint8_t led_mode;
    uint8_t r, g, b;
};
static constexpr uint8_t SetStatePayloadSize = sizeof(SetStatePayload);
#pragma pack(pop)

} // namespace comms
