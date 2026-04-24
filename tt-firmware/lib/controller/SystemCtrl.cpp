#include "SystemCtrl.h"
#include "LEDCtrl.h"
#include <Packet.h>
#include <Arduino.h>
#ifdef ARDUINO_ARCH_ESP8266
#include <ESP8266WiFi.h>
#else
#include <WiFi.h>
#endif
#include <espnow.h>
#include <math.h>
#include <FastLED.h>

namespace ctrl {

    SystemCtrl::SystemCtrl(const char* version) { }

    void SystemCtrl::setupLeds(CRGB* leds, uint8_t numLeds) {
        ledCtrl_ = new LEDCtrl(leds, numLeds);
        ledCtrl_->doSpotlightEffect(0, 0, 1500); //slow heartbeat
    }

    static SystemCtrl* sself = nullptr;

    void handleEspNowTx(uint8_t *mac_addr, uint8_t status) {
    }

    void handleEspNowRecv(u8 *mac_addr, u8 *data, u8 len) {
        auto res = comms::isPacketValid(data, len);
        if (sself && res == comms::PktValid) {
            const comms::PktHeader* h = reinterpret_cast<const comms::PktHeader*>(data);
            const uint8_t* payload = data + comms::PAYLOAD_OFFSET;
            sself->handlePacket(*h, payload, h->plen, MsgDest::EspNow);
        } else {
            Serial.printf("[ESP-NOW] invalid pkt len %d, res %d\n", len, (int)res);
        }
    }

    void SystemCtrl::setupESPNow() {
        WiFi.mode(WIFI_STA);
        WiFi.disconnect();

        uint8_t mac[6] = {0};
        WiFi.macAddress(mac);
        address_ = (uint16_t)(mac[4] << 8) | mac[5];
        Serial.printf("[NET] Node 0x%02X  MAC: %02X:%02X:%02X:%02X:%02X:%02X\n", address_, mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

        if (esp_now_init() != 0) {
            Serial.println("[ESP-NOW] Init FAILED");
            if (ledCtrl_) { ledCtrl_->showAlert(CRGB::Blue, 500); }
        }
        esp_now_set_self_role(ESP_NOW_ROLE_COMBO);
        sself = this;
        esp_now_register_send_cb(handleEspNowTx);
        esp_now_register_recv_cb(handleEspNowRecv);
        auto res = esp_now_add_peer(const_cast<uint8_t*>(BROADCAST_ADDR.data()), ESP_NOW_ROLE_SLAVE, 0, nullptr, 0);
        Serial.printf("ESP-NOW add peer res: %d\n", res);
    }

    void SystemCtrl::iterate(uint32_t now) {
        iterateSerial(now);
        iterateEspNow(now);
        if (ledCtrl_) {
            ledCtrl_->iterate(now);
        }
        if (extraHandler_) {
            extraHandler_->iterate(now);
        }
    }

    bool SystemCtrl::handlePacket(const comms::PktHeader& h, const uint8_t* payload, uint8_t plen, MsgDest src) {
        bool isLikelyForUs = (h.id == address_ || h.id == 0);
        if (!isForwardingNode() && !isLikelyForUs) {
            Serial.printf("[CMD] Packet id 0x%02X does not match our address (0x%02X), ignoring\n", h.id, address_);
            return false; // packet not for us, ignore
        }
        bool handled = (extraHandler_ && isLikelyForUs)? extraHandler_->handlePacket(h, payload, plen, src) : false;

        if (handled) {
            // handled by extra handler, do nothing here
        } else if (isLikelyForUs && h.type == comms::CMD_VERSION) {
            sendMsg(h.id, comms::CMD_VERSION, (const uint8_t*)version_, strlen(version_), src);
        } else if (isLikelyForUs && h.type == comms::CMD_SET_STATE && plen == sizeof(comms::SetStatePayload)) {
            auto pkt = reinterpret_cast<const comms::SetStatePayload*>(payload);
            Serial.printf("[CMD] SetState for node 0x%02X: mode %d, color %08X <%d %d>\n", pkt->node_id, pkt->led_mode, pkt->color, pkt->param1, pkt->param2);
            if (ledCtrl_) {
                ledCtrl_->handleCmd(*pkt);
            }
        // TODO handle other system cmds like settings get/set, updates, etc
        } else if (isForwardingNode()) { // forward to other interface
            auto dest = (src == MsgDest::Uart) ? MsgDest::EspNow : MsgDest::Uart;
            sendMsg(h.id, h.type, payload, plen, dest);
        } else { //unhandled
            Serial.printf("[CMD] Unhandled pkt: id 0x%02X type %d plen %d src %d\n", h.id, h.type, plen, (int)src);
            return false;
        }
        lastHandledCmd_ = millis();
        return true;
    }

    void SystemCtrl::sendMsg(uint8_t id, uint8_t type, const uint8_t* payload, uint8_t plen, MsgDest to) {
        uint8_t buf[comms::FRAME_MAX] = {0};
        comms::pktSerialize(id, type, payload, plen, buf, sizeof(buf));

        uint8_t to8 = static_cast<uint8_t>(to);
        if (to8 & (uint8_t)MsgDest::Uart) {
            Serial.write(buf, plen + comms::PKT_OVERHEAD);
        }
        if (to8 & (uint8_t)MsgDest::EspNow) {
            esp_now_send(espDestAddr_.data(), buf, plen + comms::PKT_OVERHEAD);
        }
    }

    void SystemCtrl::iterateSerial(uint32_t now) {
        if (readBinaryProtocolToBuffer(&Serial, serBuf_, serPos_, sizeof(serBuf_))) {
            const comms::PktHeader* h = reinterpret_cast<const comms::PktHeader*>(serBuf_);
            const uint8_t* payload = serBuf_ + comms::PAYLOAD_OFFSET;
            handlePacket(*h, payload, h->plen, MsgDest::Uart);
            serPos_ = 0;
        }
    }

    void SystemCtrl::iterateEspNow(uint32_t now) {
        if ((now - lastHandledCmd_) > idlePingPeriod_ && (now - idlePingLastSent_) > idlePingPeriod_) {
            if (ledCtrl_) {
                ledCtrl_->showAlert(0x440011, 600, 1200); //dark violet quick alert to indicate idle ping
            }
            sendMsg(0, comms::CMD_PING, nullptr, 0, MsgDest::All);
            Serial.println("[NET] Sent idle ping");
            idlePingLastSent_ = now;
        }
    }

    bool SystemCtrl::readBinaryProtocolToBuffer(HardwareSerial* p, uint8_t* buf, uint8_t &pos, uint16_t bufSize) {
        while (p->available()) {
            uint8_t b = p->read();
            if (pos == 0 && b != comms::STARTBYTE) continue;

            buf[pos++] = b;

            comms::PktReadState state = comms::isPacketValid(buf, pos);
            if (state == comms::PktValid) {
                return true;
            } else if (pos > bufSize || state == comms::PktInvalid) {
                pos = 0; //reset
            }
        }
        return false;
    }

} // namespace ctrl
