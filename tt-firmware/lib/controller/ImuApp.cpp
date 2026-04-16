#include "ImuApp.h"
#include "SystemCtrl.h"
#include <math.h>

namespace ctrl {

ImuApp::ImuApp() { }

void ImuApp::setup(SystemCtrl* sys) {
    sys_ = sys;
    imu_.initialize();
    // _lastBeatMs = millis();
}

bool ImuApp::imuOk() {
    return imu_.testConnection();
}

void ImuApp::iterate() {
    uint32_t now = millis();

    if (now - lastImuReadMs_ >= IMU_INTERVAL_MS) {
        lastImuReadMs_ = now;
        readImu();
    }
    if (now - lastSendMs_ >= SEND_INTERVAL_MS) {
        lastSendMs_ = now;
        sendImu();
    }
}

void ImuApp::readImu() {
    comms::ImuPayload p = {};
    int16_t gz = 0;
    imu_.getMotion6(&p.ax, &p.ay, &p.az, &p.gx, &p.gy, &gz);

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
