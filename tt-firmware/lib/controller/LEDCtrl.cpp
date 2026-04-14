#include "LEDCtrl.h"
#include <Arduino.h>
#include <math.h>
#include <FastLED.h>

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
    void LEDCtrl::doSpotlightEffect(float dir, float magnitude, uint32_t period) {
        if (alertOverrideEndMs_) return;
        ledMode_ = LedMode::Spotlight;
        ledEffectParamA_ = dir;
        ledEffectParamB_ = magnitude;
        ledParamPeriod_ = period;
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
            float phase = (otime % period) / (float)period;
            float p1       = expf(-powf((phase - 0.15f) / 0.06f, 2.0f));
            float p2       = expf(-powf((phase - 0.35f) / 0.06f, 2.0f)) * 0.6f;
            uint8_t redVal = (uint8_t)constrain((p1 + p2) * 60.0f, 0.0f, 50.0f);

            const auto dir = ledEffectParamA_;
            const auto magnitude = ledEffectParamB_;
            float center   = ((dir + PI) / (2.0f * PI)) * numLeds_;
            float bright   = constrain(magnitude / (PI / 2.0f), 0.0f, 1.0f);

            for (uint8_t i = 0; i < numLeds_; i++) {
                float d = (float)i - center;
                while (d >  numLeds_ / 2.0f) d -= numLeds_;
                while (d < -numLeds_ / 2.0f) d += numLeds_;
                uint8_t blue = (uint8_t)(expf(-(d*d) / (2.0f * 3.5f * 3.5f)) * bright * 220.0f);
                leds_[i] = CRGB(redVal, 0, blue);
            }
        }
        FastLED.show();
        lastLedUpdate_ = now;
    }

} // namespace ctrl
