#include "SystemCtrl.h"
#include "LEDCtrl.h"
#include <Packet.h>
#include <Arduino.h>
#ifdef ARDUINO_ARCH_ESP8266
#include <ESP8266WiFi.h>
#include <Updater.h>
#else
#include <WiFi.h>
#endif
#include <espnow.h>
#include <math.h>
#include <FastLED.h>

namespace ctrl {

    SystemCtrl::SystemCtrl(const char* version) : version_(version) { }

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
        if (isForwardingNode() && h.to != address_) {  //not specifically for us? forward to other interface
            auto dest = (src == MsgDest::Uart) ? MsgDest::EspNow : MsgDest::Uart;
            sendMsg(h.to, h.type, payload, plen, dest, h.from); //forward and include the from address
            return true;
        }

        bool isLikelyForUs = (h.to == address_ || h.to == 0);
        if (!isForwardingNode() && !isLikelyForUs) {
            Serial.printf("[CMD] Packet id 0x%02X does not match our address (0x%02X), ignoring\n", h.to, address_);
            return false; // packet not for us, ignore
        }
        bool handled = (extraHandler_ && isLikelyForUs)? extraHandler_->handlePacket(h, payload, plen, src) : false;

        if (handled) {
            // handled by extra handler, do nothing here
        } else if (isLikelyForUs && h.type == comms::CMD_VERSION) {
            sendMsg(h.from, comms::CMD_VERSION, (const uint8_t*)version_, strlen(version_), src);
        } else if (isLikelyForUs && h.type == comms::CMD_SET_STATE && plen == sizeof(comms::SetStatePayload)) {
            auto pkt = reinterpret_cast<const comms::SetStatePayload*>(payload);
            Serial.printf("[CMD] SetState for node mode %d, color %08X <%d %d>\n", pkt->led_mode, pkt->color, pkt->param1, pkt->param2);
            if (ledCtrl_) {
                ledCtrl_->handleCmd(*pkt);
            }
        } else if (isLikelyForUs && h.type == comms::CMD_UPDATE_INIT && plen == sizeof(comms::UpdateInitPayload)) {
            auto pkt = reinterpret_cast<const comms::UpdateInitPayload*>(payload);
            handled = handleUpdateInit(h, *pkt, src);
        } else if (isLikelyForUs && h.type == comms::CMD_UPDATE_PAYLOAD && plen >= sizeof(comms::UpdatePayloadHeader)) {
            handled = handleUpdatePayload(h, payload, plen, src);
        // TODO handle other system cmds like settings get/set, updates, etc
        } else { //unhandled
            Serial.printf("[CMD] Unhandled pkt: id 0x%02X type %d plen %d src %d\n", h.to, h.type, plen, (int)src);
            return false;
        }
        lastHandledCmd_ = millis();
        return true;
    }

    void SystemCtrl::sendMsg(uint16_t to_id, uint8_t type, const uint8_t* payload, uint8_t plen, MsgDest to_dest, uint16_t fromaddr) {
        uint8_t buf[comms::FRAME_MAX] = {0};
        comms::pktSerialize(fromaddr? fromaddr : address_, to_id, type, payload, plen, buf, sizeof(buf));

        uint8_t to8 = static_cast<uint8_t>(to_dest);
        if (to8 & (uint8_t)MsgDest::Uart) {
            Serial.write(buf, plen + comms::PKT_OVERHEAD);
        }
        if (to8 & (uint8_t)MsgDest::EspNow) {
            esp_now_send(espDestAddr_.data(), buf, plen + comms::PKT_OVERHEAD);
        }
    }

    void SystemCtrl::sendTxt(uint16_t to_id, MsgDest dest, uint8_t type, const char* fmt, ...) {
        char buf[128] = {0};
        va_list args;
        va_start(args, fmt);
        vsnprintf(buf, sizeof(buf), fmt, args);
        va_end(args);
        sendMsg(to_id, type, (const uint8_t*)buf, strlen(buf), dest);
        Serial.write(buf, strlen(buf));
    }

    void SystemCtrl::iterateSerial(uint32_t now) {
        if (readBinaryProtocolToBuffer(&Serial, serBuf_, serPos_, sizeof(serBuf_))) {
            const comms::PktHeader* h = reinterpret_cast<const comms::PktHeader*>(serBuf_);
            const uint8_t* payload = serBuf_ + comms::PAYLOAD_OFFSET;
            if (handlePacket(*h, payload, h->plen, MsgDest::Uart)) {
                lastHandledCmd_ = now;
            }
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

    bool SystemCtrl::handleUpdateInit(const comms::PktHeader& h, const comms::UpdateInitPayload& init, MsgDest from) {
        // Base implementation just acknowledges. Override to handle actual update logic.
        Serial.printf("[OTA] Update init received: %u chunks, total size %u bytes\n", init.total_chunks, init.total_size);

        #ifdef ARDUINO_ARCH_ESP8266
        if (!Update.begin(updateInited_.total_size)) {
            Serial.printf("[OTA] Update.begin failed: %d\n", Update.getError());
            sendTxt(h.from, from, comms::ERROR, "Update.begin failed %d", Update.getError());
        } else {
            updateInited_ = init; // save update context
            Serial.println("[OTA] Update begun");
            sendMsg(0, comms::CMD_UPDATE_INIT, nullptr, 0, from); //ack
        }
        #else
            Serial.println("[OTA] ESP8266 OTA only");
            sendTxt(h.from, from, comms::ERROR, "Update not supported");
        #endif
        return true;
    }

    bool SystemCtrl::handleUpdatePayload(const comms::PktHeader& h, const uint8_t* payload, uint8_t plen, MsgDest from) {
        auto hdr = reinterpret_cast<const comms::UpdatePayloadHeader*>(payload);
        const uint8_t chunkDataLen = plen - comms::UpdatePayloadHeaderSize;
        const uint8_t* chunkData = payload + comms::UpdatePayloadHeaderSize;
        Serial.printf("[OTA] Payload seq=%u, chunkLen=%u\n", hdr->sequence, chunkDataLen);

        #ifdef ARDUINO_ARCH_ESP8266
        if (!Update.isRunning()) {
            sendTxt(h.from, from, comms::ERROR, "Update not started");
            return true;
        } else if (hdr->sequence != updateLastSeq_ + 1) {
            sendTxt(h.from, from, comms::ERROR, "Update bad seq %d", updateLastSeq_);
            return true;
        }

        const size_t written = Update.write((uint8_t*)chunkData, chunkDataLen);

        if (written != chunkDataLen || Update.hasError()) {
            sendTxt(h.from, from, comms::ERROR, "[OTA] Write fail %u / %u\n", (unsigned)written, (unsigned)chunkDataLen);
            return true;
        }
        bool hasError = Update.hasError();

        if (hdr->sequence >= updateInited_.total_chunks) { //finished!
            if (!Update.end()) {
                hasError = true; //fall through to send error
            } else {
                Serial.println("[OTA] Update complete, rebooting...");
                delay(100);
                ESP.restart();
            }
        }

        if (hasError) {
            sendTxt(h.from, from, comms::ERROR, "[OTA] err %s", Update.getErrorString().c_str());
        } else {
            sendMsg(h.from, comms::CMD_UPDATE_PAYLOAD, payload, sizeof(comms::UpdatePayloadHeader), from); //ack
        }
        return true;
        #else
        Serial.println("[OTA] ESP8266 OTA only");
        return false;
        #endif
    }

} // namespace ctrl
