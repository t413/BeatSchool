#include "LEDCtrl.h"
#include <Arduino.h>
#include <math.h>
#include <FastLED.h>
#include <Packet.h>

namespace ctrl {

    LEDCtrl::LEDCtrl(CRGB* leds, uint8_t numLeds) {
        leds_ = leds;
        numLeds_ = numLeds;
        ledParamClr_ = CRGB::Red;
    }

    CRGB fromU32(uint32_t c) { return CRGB((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF); }


    void LEDCtrl::showAlert(uint32_t color, uint32_t period, uint32_t duration) {
        alertColor_ = color;
        alertPeriod_ = period;
        alertOverrideEndMs_ = millis() + duration;
    }


    void LEDCtrl::off() {
        if (alertOverrideEndMs_) return;
        ledMode_ = LedMode::OFF;
    }
    void LEDCtrl::doSolidEffect(uint32_t color) {
        if (alertOverrideEndMs_) return;
        ledMode_ = LedMode::Solid;
        ledParamClr_ = color;
    }
    void LEDCtrl::doBeatEffect(uint32_t color, uint32_t period) {
        if (alertOverrideEndMs_) return;
        ledMode_ = LedMode::Beat;
        ledParamClr_ = color;
        ledParamPeriod_ = period;
    }
    void LEDCtrl::doSpotlightEffect(float pitch, float roll, uint32_t period) {
        if (alertOverrideEndMs_) return;
        ledMode_ = LedMode::Spotlight;
        ledEffectParamA_ = pitch != NOT_SET? pitch : ledEffectParamA_;
        ledEffectParamB_ = roll != NOT_SET? roll : ledEffectParamB_;
        ledParamPeriod_ = period != NOT_SET? period : ledParamPeriod_;
    }

    void LEDCtrl::handleCmd(const comms::SetStatePayload& pkt) {
        uint32_t clr = pkt.color != NOT_SET? pkt.color : ledParamClr_;
        switch ((LedMode)pkt.led_mode) {
            case LedMode::OFF:       off(); break;
            case LedMode::Solid:     doSolidEffect(clr); break;
            case LedMode::Beat:      doBeatEffect(clr, pkt.param1); break;
            case LedMode::Spotlight: doSpotlightEffect(-1, -1, pkt.param1); break;
        }
    }

    void LEDCtrl::iterate(const uint32_t now) {
        if (alertOverrideEndMs_ && now > alertOverrideEndMs_) {
            alertOverrideEndMs_ = 0; //clear
        }
        const auto otime = now + effectTimeSyncOffset_;
        auto clr = fromU32(alertOverrideEndMs_ ? alertColor_ : ledParamClr_);
        const uint32_t period = alertOverrideEndMs_ ? alertPeriod_ : ledParamPeriod_;
        const auto mode = alertOverrideEndMs_ ? LedMode::Beat : ledMode_;

        if (mode == LedMode::OFF) {
            fill_solid(leds_, numLeds_, CRGB::Black);

        } else if (mode == LedMode::Solid) {
            fill_solid(leds_, numLeds_, clr);

        } else if (mode == LedMode::Beat) {
            float phase = (otime % period) / (float)period;
            uint8_t val = (sin(phase * 2 * PI) + 1) / 2 * 255;
            fill_solid(leds_, numLeds_, clr.nscale8(val));

        } else if (mode == LedMode::Spotlight) {
            bool doHeartbeat = false;
            uint8_t redVal = 0;

            if (doHeartbeat) {
                float phase = (otime % period) / (float)period;
                float p1       = expf(-powf((phase - 0.15f) / 0.06f, 2.0f));
                float p2       = expf(-powf((phase - 0.35f) / 0.06f, 2.0f)) * 0.6f;
                redVal = (uint8_t)constrain((p1 + p2) * 60.0f, 0.0f, 50.0f);
            }

            const float pitch = ledEffectParamA_;
            const float roll = ledEffectParamB_;

            float angle = atan2f(pitch, roll);
            float magnitude = sqrtf(pitch * pitch + roll * roll);

            const uint8_t halfLeds = numLeds_ / 2;
            float center   = ((angle + PI) / (2.0f * PI)) * halfLeds;
            float bright   = constrain(magnitude / 45.0f, 0.0f, 1.0f);
            float sigma    = 1.2f;

            for (uint8_t i = 0; i < halfLeds; i++) {
                float d = (float)i - center;
                while (d >  halfLeds / 2.0f) d -= halfLeds;
                while (d < -halfLeds / 2.0f) d += halfLeds;
                uint8_t blue = (uint8_t)(expf(-(d*d) / (2.0f * sigma * sigma)) * bright * 255.0f);
                leds_[i] = CRGB(redVal, 0, blue);
                leds_[i + halfLeds] = CRGB(redVal, 0, blue);
            }
        }
        FastLED.show();
        lastLedUpdate_ = now;
    }

} // namespace ctrl
