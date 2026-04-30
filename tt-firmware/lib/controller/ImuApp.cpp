#include "ImuApp.h"
#include "SystemCtrl.h"
#include "LedCtrl.h"
#include <MPU6050_light.h>
#include <math.h>

namespace ctrl {

ImuApp::ImuApp() { }

void ImuApp::setup(SystemCtrl* sys) {
    if (sys) {
        sys_ = sys;
        sys_->setupHandler(this);
    }
}

LEDCtrl* ImuApp::getLEDs() { return sys_->getLedCtrl(); }

bool ImuApp::trySetupImu(int imu_sda, int imu_scl, int imu_addr) {
    Serial.printf("[IMU] Testing MPU6050 on I2C (SDA: %d, SCL: %d, ADDR: 0x%02X)\n", imu_sda, imu_scl, imu_addr);
    Wire.begin(imu_sda, imu_scl);
    Wire.setClock(100000); // 100 kHz I2C clock

    Serial.println("[IMU] Scanning I2C bus...");
    byte count = 0;
    for (byte address = 1; address < 127; address++) {
        Wire.beginTransmission(address);
        if (Wire.endTransmission() == 0) {
            Serial.printf("[IMU] Found device at address 0x%02X\n", address);
            count++;
        }
    }
    if (count == 0) {
        Serial.println("[IMU] No I2C devices found");
    }
    Serial.printf("[IMU] I2C scan finished. Found %d device(s)\n", count);

    Wire.beginTransmission(imu_addr);
    if (Wire.endTransmission() != 0) {
        return false;
    }

    if (!imu_) {
        imu_ = new MPU6050(Wire);
    }
    auto res = imu_->begin();
    imu_->calcOffsets(); // keep device still
    Serial.printf("[IMU] MPU6050 initialized. testing res = %d\n", res);

    Serial.println("[IMU] Initializing gyro-only tilt tracking...");
    pitch_ = 0.0f;
    roll_ = 0.0f;
    lastImuReadMs_ = millis();

    return true;
}

void ImuApp::iterate(uint32_t now) {
    if (now - lastImuReadMs_ >= IMU_INTERVAL_MS) {
        lastImuReadMs_ = now;
        imu_->update();

        // Read gyro data (deg/s)
        float gyroX = imu_->getGyroY();  // X-axis rotation
        float gyroY = imu_->getGyroX();  // Y-axis rotation

        // Time delta in seconds
        float dt = IMU_INTERVAL_MS / 1000.0f;

        // Integrate angular velocity to get angle change
        pitch_ += gyroX * dt;
        roll_ += gyroY * dt;

        // Exponential drift-back to zero (mechanical spring-back simulation)
        pitch_ *= DRIFT_FACTOR;
        roll_ *= DRIFT_FACTOR;

        // Clamp to reasonable ranges
        pitch_ = constrain(pitch_, -90.0f, 90.0f);
        roll_ = constrain(roll_, -90.0f, 90.0f);
    }

    if (now - lastSendMs_ >= SEND_INTERVAL_MS) {
        lastSendMs_ = now;

        // Pack into payload
        comms::ImuPayload p = {
            .seq = lastPayload_.seq + 1,
            .pitch = pitch_,
            .roll = roll_,
        };
        sys_->sendMsg(0, comms::CMD_IMU_DATA, reinterpret_cast<const uint8_t*>(&p), sizeof(p), MsgDest::EspNow);
        sys_->getLedCtrl()->doSpotlightEffect(pitch_, roll_, NOT_SET);
        lastPayload_ = p;
    }
}

bool ImuApp::handlePacket(const comms::PktHeader& h, const uint8_t* payload, uint8_t plen, MsgDest from) {
    if (h.type == comms::CMD_ZERO) { //zero gyros
        imu_->calcOffsets();
        return true;
    } else if (h.type == comms::CMD_PING) {
        getLEDs()->showAlert(0x555555, 300, 600);
        return true;
    } else {
        return false;
    }
}

} // namespace ctrl
