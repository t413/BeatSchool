#pragma once
#include <cstdint>
#include <cstring>
#include <functional>

namespace comms {

struct __attribute__((__packed__)) PktHeader {
  uint8_t startbyte;
  uint16_t from;
  uint16_t to;
  uint8_t type;
  uint8_t plen;
};

static constexpr uint8_t  STARTBYTE    = 0xAC;
static constexpr uint8_t  PAYLOAD_OFFSET = sizeof(PktHeader);
static constexpr uint8_t  PKT_OVERHEAD = PAYLOAD_OFFSET + 1;
static constexpr uint8_t  FRAME_MAX    = 250;   //esp-now max payload is 250 bytes
static constexpr uint8_t  PAYLOAD_MAX  = FRAME_MAX - PKT_OVERHEAD;

enum PktReadState {
  PktUnfinished = -1,
  PktInvalid    =  0,
  PktValid      =  1
};

// Helper for payload access

PktReadState isPacketValid(const uint8_t* pkt, const uint16_t len);
uint8_t checksum(const uint8_t* buf, uint16_t len, uint8_t startval = 0);

uint8_t pktSerialize(uint16_t from, uint16_t to, uint8_t type, const uint8_t* payload, const uint8_t payloadLen, uint8_t* buf, uint16_t buflen);

// defines function to write data (like Serial.write)
using PktSendFunc = std::function<void(const uint8_t* data, uint8_t len)>;
void pktSend(const PktHeader& hdr, const uint8_t* payload, uint8_t plen, PktSendFunc sendFunc);


// ============================================================
//  Payload types / structs
// ============================================================

// ---- command IDs (low byte of id field) ---------------------------
enum Cmd : uint8_t {
    CMD_PING      = 0x00,   // coord -> broadcast (or relay alive ping)
    ERROR         = 0x01,
    CMD_VERSION   = 0x02,   // get or reply with program version
    DEBUG_MSG     = 0x03,   // debug string message

    CMD_UPDATE_INIT    = 0x11,   // start OTA update, sends metadata
    CMD_UPDATE_PAYLOAD = 0x12,   // OTA update data chunk

    CMD_IMU_DATA  = 0xA1,   // node  -> coordinator
    CMD_SET_STATE = 0xA2,   // coord -> node
    CMD_ZERO      = 0xA3,   // zero gyros, etc

};

#pragma pack(push, 1)
struct __attribute__((__packed__)) ImuPayload {
    uint16_t seq;
    float pitch, roll;
};
static constexpr uint8_t ImuPayloadSize = sizeof(ImuPayload);

struct __attribute__((__packed__)) SetStatePayload {
    uint8_t led_mode;
    uint32_t color;
    uint32_t param1;
    uint32_t param2;
};
static constexpr uint8_t SetStatePayloadSize = sizeof(SetStatePayload);

// ---- OTA Update payload structures ---------------------------
struct __attribute__((__packed__)) UpdateInitPayload {
    uint16_t total_chunks;         // Total number of data chunks to follow
    uint16_t full_update_chksum;   // CRC/checksum of entire update image
    uint32_t total_size;           // Total size of update in bytes
};
static constexpr uint8_t UpdateInitPayloadSize = sizeof(UpdateInitPayload);

struct __attribute__((__packed__)) UpdatePayloadHeader {
    uint16_t sequence;             // Chunk sequence number
    uint16_t full_update_chksum;   // CRC/checksum of entire update image
};
static constexpr uint8_t UpdatePayloadHeaderSize = sizeof(UpdatePayloadHeader);
static constexpr uint8_t UPDATE_CHUNK_MAX = PAYLOAD_MAX - UpdatePayloadHeaderSize;

#pragma pack(pop)

} // namespace comms
