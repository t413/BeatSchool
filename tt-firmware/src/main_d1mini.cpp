#include "version.h"
#include <Arduino.h>
#include <FastLED.h>
#include <Wire.h>
#include <SystemCtrl.h>
#include <NodeController.h>

#define LED_PIN      2
#define NUM_LEDS     45
#define IMU_SDA      4
#define IMU_SCL      5
#define IMU_ADDR     0x68

CRGB leds[NUM_LEDS];

ctrl::SystemCtrl systemctrl(GIT_VERSION);

bool detectHasIMU() {
    Wire.begin(IMU_SDA, IMU_SCL);
    Wire.beginTransmission(IMU_ADDR);
    return (Wire.endTransmission() == 0) ? true : false;
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n[Setup] Booting");

    FastLED.addLeds<WS2812B, LED_PIN, GRB>(leds, NUM_LEDS)
           .setCorrection(TypicalLEDStrip);
    FastLED.setBrightness(80);
    systemctrl.setupLeds(leds, NUM_LEDS);
    systemctrl.setupESPNow();

    bool hasIMU = detectHasIMU();

    if (hasIMU) {
        Serial.println("[IMU] Detected MPU6050 on I2C");
        //TODO add NodeController or similar handler
        // if (!nodeCtrl->imuOk()) {
    }
    Serial.printf("\n[Setup] Booted version %s\n", GIT_VERSION);
}

void loop() {
    systemctrl.loop();
    yield();
}
