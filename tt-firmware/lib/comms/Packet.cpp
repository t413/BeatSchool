#include "Packet.h"

namespace comms {

uint8_t checksum(const uint8_t* buf, uint16_t len, uint8_t startval) {
    uint8_t cs = startval;
    for (uint16_t i = 0; i < len; i++) cs ^= buf[i];
    return cs;
}

PktReadState isPacketValid(const uint8_t* pkt, const uint16_t len) {
    if (len < PKT_OVERHEAD) return PktUnfinished;

    const PktHeader* h = reinterpret_cast<const PktHeader*>(pkt);
    if (h->startbyte != STARTBYTE) return PktInvalid;

    uint16_t totalExpected = h->plen + PKT_OVERHEAD;
    if (len < totalExpected) return PktUnfinished;

    if (checksum(pkt, totalExpected - 1) != pkt[totalExpected - 1]) return PktInvalid;
    return PktValid;
}

uint8_t pktSerialize(uint8_t id, uint8_t type, const uint8_t* payload, const uint8_t payloadLen, uint8_t* buf, uint16_t buflen) {
    if (payloadLen > PAYLOAD_MAX || buflen < payloadLen + PKT_OVERHEAD) return 0;

    PktHeader* h = reinterpret_cast<PktHeader*>(buf);
    *h = {STARTBYTE, id, type, payloadLen};
    if (payload && payloadLen > 0) {
        memcpy(buf + PAYLOAD_OFFSET, payload, payloadLen);
    }
    buf[PAYLOAD_OFFSET + payloadLen] = checksum(buf, PAYLOAD_OFFSET + payloadLen);
    return PAYLOAD_OFFSET + payloadLen + 1;
}

void pktSend(const PktHeader& hdr, const uint8_t* payload, uint8_t plen, PktSendFunc sendFunc) {
    uint8_t chk = 0;
    auto hdrData = reinterpret_cast<const uint8_t*>(&hdr);
    sendFunc(hdrData, sizeof(hdr));
    chk = checksum(hdrData, sizeof(hdr), chk);
    if (payload && plen > 0) {
        sendFunc(payload, plen);
        chk = checksum(payload, plen, chk);
    }
    sendFunc(&chk, 1);
}

} // namespace comms
