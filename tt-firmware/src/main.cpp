#include "version.h"
#include <Arduino.h>
#include <Wire.h>
#include <ESP8266WiFi.h>
#include <espnow.h>
#include <FastLED.h>
#include <MPU6050.h>        // electroniccats/MPU6050
#include <math.h>

//GIT_VERSION pulled from platformio.ini src_build_flags, only for this file

#define LED_PIN         2
#define NUM_LEDS        45
#define LED_TYPE        WS2812B
#define COLOR_ORDER     GRB

#define IMU_SDA         4
#define IMU_SCL         5
#define IMU_ADDR        0x68

// ============================================================
//  PACKET PROTOCOL  (keep in sync with packet_spec.md)
//
//  Magic byte : 0xRC
//  Version    : 0x01
//
//  CMD_SEND_DATA  (node -> coordinator)  type=0x01
//    [magic:1][ver:1][type:1][node_id:1][seq:2][accel_x:2][accel_y:2][accel_z:2]
//    [gyro_x:2][gyro_y:2][gyro_z:2][checksum:1]  = 17 bytes
//
//  CMD_SET_STATE  (coordinator -> node)  type=0x02
//    [magic:1][ver:1][type:1][node_id:1][led_mode:1][r:1][g:1][b:1][checksum:1] = 9 bytes
//
//  CMD_PING       (coordinator -> broadcast)  type=0x03
//    [magic:1][ver:1][type:1][checksum:1]  = 4 bytes
// ============================================================
#define PKT_MAGIC_BYTE  0xAC
#define PKT_VERSION     0x01

#define CMD_SEND_DATA   0x01
#define CMD_SET_STATE   0x02
#define CMD_PING        0x03

// LED modes (from coordinator CMD_SET_STATE)
#define LED_MODE_IMU    0x00  // default: tilt + heartbeat
#define LED_MODE_SOLID  0x01  // solid color from r/g/b
#define LED_MODE_FLASH  0x02  // flash on beat cue
#define LED_MODE_CHASE  0x03  // chase animation
#define LED_MODE_OFF    0xFF

// ============================================================
//  ESP-NOW STATE
// ============================================================
// Broadcast address — all nodes receive, coordinator filters by node_id
uint8_t broadcastAddr[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// Node ID derived from last byte of MAC
uint8_t nodeId = 0;

// Coordinator MAC learned from first CMD_SET_STATE or CMD_PING received
// Until learned, we broadcast everything.
uint8_t coordinatorMac[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
bool coordinatorKnown = false;

// ============================================================
//  IMU STATE
// ============================================================
MPU6050 imu;

struct ImuSample {
    int16_t ax, ay, az;
    int16_t gx, gy, gz;
};
ImuSample lastSample = {};

// Tilt angle (radians) derived from accel, used for LED ring
float tiltAngle = 0.0f;   // 0 = upright, ±PI = fully inverted
float tiltDir   = 0.0f;   // direction angle around Z axis (0..2PI)

// ============================================================
//  LED STATE
// ============================================================
CRGB leds[NUM_LEDS];

uint8_t ledMode     = LED_MODE_IMU;
CRGB    solidColor  = CRGB::Black;

// Heartbeat timing
uint32_t lastBeatMs    = 0;
const uint32_t BEAT_PERIOD_MS = 1600; //commander can update
float    heartPhase    = 0.0f;

// Flash mode
bool     flashActive   = false;
uint32_t flashStartMs  = 0;
const uint32_t FLASH_DURATION_MS = 150;

// ============================================================
//  TIMING
// ============================================================
uint32_t lastImuReadMs  = 0;
uint32_t lastSendMs     = 0;
uint16_t sendSeq        = 0;

const uint32_t IMU_READ_INTERVAL_MS  = 20;   // 50 Hz
const uint32_t SEND_INTERVAL_MS      = 50;   // 20 Hz over ESP-Now

// ============================================================
//  UTILITY: simple XOR checksum over buf[0..len-1]
// ============================================================
uint8_t calcChecksum(const uint8_t* buf, size_t len) {
    uint8_t cs = 0;
    for (size_t i = 0; i < len; i++) cs ^= buf[i];
    return cs;
}

// ============================================================
//  ESP-NOW CALLBACKS
// ============================================================
void onDataSent(uint8_t* mac, uint8_t status) {
    // optional: blink onboard LED on fail
    (void)mac; (void)status;
}

void onDataRecv(uint8_t* mac, uint8_t* data, uint8_t len) {
    if (len < 4) return;
    if (data[0] != PKT_MAGIC_BYTE) return;
    if (data[1] != PKT_VERSION)    return;

    uint8_t cmd = data[2];
    uint8_t cs  = data[len - 1];
    if (calcChecksum(data, len - 1) != cs) return;  // bad checksum

    if (cmd == CMD_PING && len == 4) {
        // Learn coordinator MAC if not yet known
        if (!coordinatorKnown) {
            memcpy(coordinatorMac, mac, 6);
            esp_now_add_peer(coordinatorMac, ESP_NOW_ROLE_CONTROLLER, 1, NULL, 0);
            coordinatorKnown = true;
        }
        return;
    }

    if (cmd == CMD_SET_STATE && len == 9) {
        // data[3] = target node_id (0xFF = all)
        uint8_t target = data[3];
        if (target != nodeId && target != 0xFF) return;

        // Learn coordinator if not yet known
        if (!coordinatorKnown) {
            memcpy(coordinatorMac, mac, 6);
            esp_now_add_peer(coordinatorMac, ESP_NOW_ROLE_CONTROLLER, 1, NULL, 0);
            coordinatorKnown = true;
        }

        ledMode    = data[4];
        solidColor = CRGB(data[5], data[6], data[7]);

        if (ledMode == LED_MODE_FLASH) {
            flashActive   = true;
            flashStartMs  = millis();
        }
    }
}

// ============================================================
//  SEND IMU PACKET
// ============================================================
void sendImuPacket() {
    uint8_t buf[17];
    buf[0]  = PKT_MAGIC_BYTE;
    buf[1]  = PKT_VERSION;
    buf[2]  = CMD_SEND_DATA;
    buf[3]  = nodeId;
    buf[4]  = (sendSeq >> 8) & 0xFF;
    buf[5]  = sendSeq & 0xFF;
    // Raw int16 values, big-endian
    buf[6]  = (lastSample.ax >> 8) & 0xFF; buf[7]  = lastSample.ax & 0xFF;
    buf[8]  = (lastSample.ay >> 8) & 0xFF; buf[9]  = lastSample.ay & 0xFF;
    buf[10] = (lastSample.az >> 8) & 0xFF; buf[11] = lastSample.az & 0xFF;
    buf[12] = (lastSample.gx >> 8) & 0xFF; buf[13] = lastSample.gx & 0xFF;
    buf[14] = (lastSample.gy >> 8) & 0xFF; buf[15] = lastSample.gy & 0xFF;
    // Note: gz omitted to fit; add if needed and bump version
    buf[16] = calcChecksum(buf, 16);

    sendSeq++;
    uint8_t* dest = coordinatorKnown ? coordinatorMac : broadcastAddr;
    esp_now_send(dest, buf, sizeof(buf));
}

// ============================================================
//  IMU READ + TILT CALCULATION
// ============================================================
void readImu() {
    imu.getMotion6(
        &lastSample.ax, &lastSample.ay, &lastSample.az,
        &lastSample.gx, &lastSample.gy, &lastSample.gz
    );

    // Normalize accel to floats (MPU6050 default ±2g, 16384 LSB/g)
    float ax = lastSample.ax / 16384.0f;
    float ay = lastSample.ay / 16384.0f;
    float az = lastSample.az / 16384.0f;

    // Tilt magnitude from vertical (0 = upright, PI/2 = on its side)
    float horiz = sqrtf(ax * ax + ay * ay);
    tiltAngle = atan2f(horiz, fabsf(az));

    // Direction of lean around the ring
    tiltDir = atan2f(ay, ax);  // -PI..PI, map to 0..NUM_LEDS
}

// ============================================================
//  LED RENDERING
// ============================================================

// Gaussian bell curve weight: distance d (in LEDs) from center
// sigma controls spread width
float bellWeight(float d, float sigma) {
    return expf(-(d * d) / (2.0f * sigma * sigma));
}

void renderImuMode() {
    // --- Heartbeat background in red ---
    uint32_t now = millis();
    float phase = fmodf((float)(now - lastBeatMs) / (float)BEAT_PERIOD_MS, 1.0f);

    // Double-pulse heartbeat envelope: two quick peaks at ~0.15 and ~0.35 of period
    float pulse1 = expf(-powf((phase - 0.15f) / 0.06f, 2.0f));
    float pulse2 = expf(-powf((phase - 0.35f) / 0.06f, 2.0f)) * 0.6f;
    float heartbeat = (pulse1 + pulse2);  // 0..1.6, clamp below

    uint8_t redVal = (uint8_t)(constrain(heartbeat * 60.0f, 0.0f, 50.0f));  // subtle, not blinding

    // --- Tilt indicator in blue, bell curve spread ---
    // Map tilt direction (-PI..PI) to a float LED index (0..NUM_LEDS)
    float centerLed = ((tiltDir + PI) / (2.0f * PI)) * NUM_LEDS;

    // Tilt magnitude controls brightness (0 = upright = dim, PI/2 = tilted = bright)
    float tiltBrightness = constrain(tiltAngle / (PI / 2.0f), 0.0f, 1.0f);
    float sigma = 3.5f;  // spread in LEDs; adjust to taste

    for (int i = 0; i < NUM_LEDS; i++) {
        // Shortest angular distance on the ring
        float d = (float)i - centerLed;
        // Wrap distance for circular ring
        while (d >  NUM_LEDS / 2.0f) d -= NUM_LEDS;
        while (d < -NUM_LEDS / 2.0f) d += NUM_LEDS;

        float w = bellWeight(d, sigma) * tiltBrightness;
        uint8_t blueVal = (uint8_t)(w * 220.0f);

        leds[i] = CRGB(redVal, 0, blueVal);
    }
}

void renderSolidMode() {
    fill_solid(leds, NUM_LEDS, solidColor);
}

void renderFlashMode() {
    uint32_t elapsed = millis() - flashStartMs;
    if (elapsed >= FLASH_DURATION_MS) {
        flashActive = false;
        ledMode = LED_MODE_IMU;  // return to default after flash
        return;
    }
    // Sharp white flash that decays quickly
    float t = 1.0f - ((float)elapsed / FLASH_DURATION_MS);
    uint8_t v = (uint8_t)(t * t * 255.0f);  // quadratic decay
    fill_solid(leds, NUM_LEDS, CRGB(v, v, v));
}

void renderChaseMode() {
    static uint8_t chasePos = 0;
    static uint32_t lastChaseMs = 0;
    uint32_t now = millis();
    if (now - lastChaseMs > 40) {
        chasePos = (chasePos + 1) % NUM_LEDS;
        lastChaseMs = now;
    }
    fadeToBlackBy(leds, NUM_LEDS, 60);
    leds[chasePos] = solidColor ? solidColor : CRGB::Cyan;
}

void updateLeds() {
    switch (ledMode) {
        case LED_MODE_IMU:
            renderImuMode();
            break;
        case LED_MODE_SOLID:
            renderSolidMode();
            break;
        case LED_MODE_FLASH:
            if (flashActive) renderFlashMode();
            else renderImuMode();
            break;
        case LED_MODE_CHASE:
            renderChaseMode();
            break;
        case LED_MODE_OFF:
            fill_solid(leds, NUM_LEDS, CRGB::Black);
            break;
        default:
            renderImuMode();
            break;
    }
    FastLED.show();
}

// ============================================================
//  SETUP
// ============================================================
void setup() {
    Serial.begin(115200);
    delay(10);
    Serial.printf("\n[TTeacher] Node booting version %s\n", GIT_VERSION);

    // --- FastLED ---
    FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS)
           .setCorrection(TypicalLEDStrip);
    FastLED.setBrightness(80);
    fill_solid(leds, NUM_LEDS, CRGB::Black);
    FastLED.show();

    // --- I2C + IMU ---
    Wire.begin(IMU_SDA, IMU_SCL);
    imu.initialize();
    if (!imu.testConnection()) {
        Serial.println("[IMU] MPU6050 connection FAILED");
        // Blink red to signal error
        for (int i = 0; i < 5; i++) {
            fill_solid(leds, NUM_LEDS, CRGB::Red);
            FastLED.show();
            delay(200);
            fill_solid(leds, NUM_LEDS, CRGB::Black);
            FastLED.show();
            delay(200);
        }
    } else {
        Serial.println("[IMU] MPU6050 OK");
        // Brief green confirmation
        fill_solid(leds, NUM_LEDS, CRGB(0, 40, 0));
        FastLED.show();
        delay(300);
        fill_solid(leds, NUM_LEDS, CRGB::Black);
        FastLED.show();
    }

    // --- WiFi in STA mode (required for ESP-Now) ---
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();

    // Derive node ID from last byte of MAC
    uint8_t mac[6];
    WiFi.macAddress(mac);
    nodeId = mac[5];
    Serial.printf("[NET] Node ID: 0x%02X  MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
        nodeId, mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

    // --- ESP-Now ---
    if (esp_now_init() != 0) {
        Serial.println("[ESP-NOW] Init FAILED");
        while (true) delay(1000);
    }
    esp_now_set_self_role(ESP_NOW_ROLE_COMBO);
    esp_now_register_send_cb(onDataSent);
    esp_now_register_recv_cb(onDataRecv);

    // Add broadcast peer so we can always send to it
    esp_now_add_peer(broadcastAddr, ESP_NOW_ROLE_SLAVE, 1, NULL, 0);

    Serial.println("[TTeacher] Ready.");
    lastBeatMs = millis();
}

// ============================================================
//  LOOP
// ============================================================
void loop() {
    uint32_t now = millis();

    // --- Read IMU at 50Hz ---
    if (now - lastImuReadMs >= IMU_READ_INTERVAL_MS) {
        lastImuReadMs = now;
        readImu();
    }

    // --- Send IMU packet at 20Hz ---
    if (now - lastSendMs >= SEND_INTERVAL_MS) {
        lastSendMs = now;
        sendImuPacket();
    }

    // --- Update LEDs every loop (FastLED.show() is the throttle) ---
    updateLeds();

    // Tiny yield to keep ESP8266 WiFi stack happy
    yield();
}
