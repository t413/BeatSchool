#pragma once
#include <PktHandler.h>
#include <Packet.h>
#include <array>

class CRGB;
class HardwareSerial;

namespace ctrl {
    class LEDCtrl;

    class SystemCtrl : public PktHandler {
    public:
        SystemCtrl(const char* version);
        virtual ~SystemCtrl() = default;

        virtual void setupLeds(CRGB* leds, uint8_t numLeds);
        virtual void setupESPNow();
        virtual void setupHandler(PktHandler* h) { extraHandler_ = h; }

        virtual void iterate(uint32_t now) override;
        virtual bool isBase() const { return true; }

        virtual bool handlePacket(const comms::PktHeader&, const uint8_t* payload, uint8_t plen, MsgDest from) override;
        virtual void sendMsg(uint16_t to_id, uint8_t type, const uint8_t* payload, uint8_t plen, MsgDest dest);
        virtual void sendTxt(uint16_t to_id, MsgDest dest, uint8_t type, const char* fmt, ...);
        virtual LEDCtrl* getLedCtrl() { return ledCtrl_; }
        virtual uint16_t getAddress() const { return address_; }
        LEDCtrl* getLEDs() { return ledCtrl_; }

    protected:
        virtual bool handleUpdateInit(const comms::PktHeader& h, const comms::UpdateInitPayload& payload, MsgDest from);
        virtual bool handleUpdatePayload(const comms::PktHeader& h, const uint8_t* payload, uint8_t plen, MsgDest from);

    protected:
        const char* version_ = nullptr;
        uint16_t address_ = 0;
        PktHandler* extraHandler_ = nullptr;
        LEDCtrl* ledCtrl_ = nullptr;

        uint8_t serBuf_[256] = {0};
        uint8_t serPos_ = 0;
        uint32_t lastHandledCmd_ = 0;
        uint32_t idlePingLastSent_ = 2000;
        uint32_t idlePingPeriod_ = 20000;

        comms::UpdateInitPayload updateInited_ = {0};
        uint16_t updateLastSeq_ = 0;

        static constexpr std::array<uint8_t, 6> BROADCAST_ADDR{ 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF };
        std::array<uint8_t, 6> espDestAddr_ = BROADCAST_ADDR;

        static bool readBinaryProtocolToBuffer(HardwareSerial* p, uint8_t* buf, uint8_t &pos, uint16_t bufSize);

        virtual void iterateSerial(uint32_t);
        virtual void iterateEspNow(uint32_t);
        virtual bool isForwardingNode() const { return extraHandler_ == nullptr; }
    };

} // namespace ctrl
