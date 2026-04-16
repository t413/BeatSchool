#include "version.h"
#include <Arduino.h>
#include <FastLED.h>
#include <Wire.h>
#include <SystemCtrl.h>
#include <ImuApp.h>

#define LED_PIN      2
#define NUM_LEDS     45
#define IMU_SDA      4
#define IMU_SCL      5
#define IMU_ADDR     0x68

CRGB leds[NUM_LEDS];

ctrl::SystemCtrl systemctrl(GIT_VERSION);
ctrl::ImuApp imuApp;

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n[Setup] Booting");

    FastLED.addLeds<WS2812B, LED_PIN, GRB>(leds, NUM_LEDS)
           .setCorrection(TypicalLEDStrip);
    FastLED.setBrightness(80);
    systemctrl.setupLeds(leds, NUM_LEDS);
    systemctrl.setupESPNow();

    Serial.println("[IMU] Testing for MPU6050 on I2C");
    if (imuApp.trySetupImu(IMU_SDA, IMU_SCL, IMU_ADDR)) {
        Serial.println("[IMU] IMU connection OK");
        imuApp.setup(&systemctrl);
    } else {
        Serial.println("[IMU] IMU initialization failed");
    }
    Serial.printf("\n[Setup] Booted version %s\n", GIT_VERSION);
}

void loop() {
    systemctrl.iterate(millis());
    yield();
}
