#pragma once
#include <cstdint>

namespace comms {
    struct PktHeader;
}

namespace ctrl {

    enum class MsgDest : uint8_t {
        Uart = 0x01,
        EspNow = 0x02,
        All = 0xFF,
    };

    class PktHandler {
    public:
        virtual bool handlePacket(const comms::PktHeader&, const uint8_t* payload, uint8_t plen, MsgDest) = 0;
    };

} // namespace ctrl
