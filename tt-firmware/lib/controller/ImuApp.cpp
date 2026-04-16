#include "ImuApp.h"
#include "SystemCtrl.h"
#include <MPU6050.h>
#include <math.h>

namespace ctrl {

ImuApp::ImuApp() { }

void ImuApp::setup(SystemCtrl* sys) {
    if (sys_) {
        sys_ = sys;
        sys_->setupHandler(this);
    }
}

bool ImuApp::trySetupImu(int imu_sda, int imu_scl, int imu_addr) {
    Wire.begin(imu_sda, imu_scl);
    Wire.beginTransmission(imu_addr);
    if (Wire.endTransmission() == 0) {
        imu_ = new MPU6050(imu_addr);
        imu_->initialize();
        return imu_->testConnection();
    } else {
        return false;
    }
}

void ImuApp::iterate(uint32_t now) {
    if (now - lastImuReadMs_ >= IMU_INTERVAL_MS) {
        lastImuReadMs_ = now;
        readImu();
    }
    if (now - lastSendMs_ >= SEND_INTERVAL_MS) {
        lastSendMs_ = now;
        sendImu();
    }
}

bool ImuApp::handlePacket(const comms::PktHeader&, const uint8_t* payload, uint8_t plen, MsgDest from) {
    return false;
}

void ImuApp::readImu() {
    comms::ImuPayload p = {};
    int16_t gz = 0;
    imu_->getMotion6(&p.ax, &p.ay, &p.az, &p.gx, &p.gy, &gz);

    float fax = p.ax / 16384.0f;
    float fay = p.ay / 16384.0f;
    float faz = p.az / 16384.0f;
    float horiz = sqrtf(fax*fax + fay*fay);
    tiltAngle_ = atan2f(horiz, fabsf(faz));
    tiltDir_   = atan2f(fay, fax);
    lastPayload_ = p;
}

void ImuApp::sendImu() {
    if (sys_ == nullptr) return;
    sys_->sendMsg(0, comms::CMD_IMU_DATA, reinterpret_cast<const uint8_t*>(&lastPayload_), sizeof(lastPayload_), MsgDest::All);
}

} // namespace RC
