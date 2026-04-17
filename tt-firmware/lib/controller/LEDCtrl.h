#pragma once
#include <cstdint>

class CRGB;
namespace comms { struct SetStatePayload; }

namespace ctrl {

    enum class LedMode : uint8_t {
        OFF = 0,
        Solid = 1,
        Beat = 2,
        Spotlight = 3,
    };

    #define NOT_SET (-1)

    class LEDCtrl {
    public:
        LEDCtrl(CRGB* leds, uint8_t numLeds);
        ~LEDCtrl() = default;

        void iterate(const uint32_t now);

        void showAlert(uint32_t color, uint32_t period, uint32_t duration = 2000);
        void off();
        void doSolidEffect(uint32_t color);
        void doBeatEffect(uint32_t color, uint32_t period);
        void doSpotlightEffect(float pitch=NOT_SET, float roll=NOT_SET, uint32_t period=NOT_SET);
        void handleCmd(const comms::SetStatePayload&);

    protected:
        CRGB*    leds_ = nullptr;
        uint8_t  numLeds_ = 0;
        uint32_t lastLedUpdate_ = 0;
        uint32_t effectTimeSyncOffset_ = 0;
        uint32_t alertColor_ = 0, alertPeriod_ = 0;
        uint32_t alertOverrideEndMs_ = 0;

        LedMode ledMode_ = LedMode::OFF;
        uint32_t ledParamClr_ = 0;
        uint32_t ledParamPeriod_ = 1000;
        float ledEffectParamA_ = 0;
        float ledEffectParamB_ = 0;

    };

} // namespace ctrl
