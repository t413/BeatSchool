#include <PktHandler.h>
#include <Packet.h>
#include <Arduino.h>

class MPU6050_Base;

namespace ctrl {
    class SystemCtrl;

    class ImuApp : public PktHandler {
    public:
        ImuApp();

        bool trySetupImu(int imu_sda, int imu_scl, int imu_addr);
        void setup(SystemCtrl*);
        void iterate(uint32_t now);

        virtual bool handlePacket(const comms::PktHeader&, const uint8_t* payload, uint8_t plen, MsgDest from) override;

    private:
        static constexpr uint32_t IMU_INTERVAL_MS  = 20;   // 50 Hz
        static constexpr uint32_t SEND_INTERVAL_MS = 50;   // 20 Hz

        SystemCtrl* sys_ = nullptr;
        MPU6050_Base* imu_ = nullptr;

        comms::ImuPayload lastPayload_ = {};
        uint32_t lastImuReadMs_ = 0, lastSendMs_ = 0;
        float tiltAngle_ = 0;
        float tiltDir_ = 0;

        void readImu();
        void sendImu();
    };

} // namespace RC
