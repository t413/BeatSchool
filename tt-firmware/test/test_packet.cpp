#include <gtest/gtest.h>
#include <vector>
#include <Packet.h>

using namespace std;
using namespace comms;

TEST(PacketTest, Checksum) {
    uint8_t data[] = {0xAC, 0x01, 0x02, 0x03};
    EXPECT_EQ(checksum(data, 4), 0x5F);
}

TEST(PacketTest, ValidPacket) {
    // Header: Start(0xAC), from(0x05), to(0) Type(0x02), Plen(0x01)
    // Payload: 0xFF
    uint8_t pkt[] = {0xAC, 0x05, 0x00, 0x00, 0x00, 0x02, 0x01, 0xFF, 0x9F};
    EXPECT_EQ(checksum(pkt, sizeof(pkt) - 1), pkt[sizeof(pkt) - 1]);
    EXPECT_EQ(isPacketValid(pkt, sizeof(pkt)), PktValid);
}

TEST(PacketTest, InvalidStartByte) {
    uint8_t pkt[] = {0xFF, 0x00, 0x05, 0x00, 0x00, 0x02, 0x01, 0xFF, 0x55};
    EXPECT_EQ(isPacketValid(pkt, sizeof(pkt)), PktInvalid);
}

TEST(PacketTest, UnfinishedPacket) {
    uint8_t pkt[] = {0xAC, 0x05, 0x00, 0x00, 0x00, 0x02, 0x01}; // Missing payload and checksum
    EXPECT_EQ(isPacketValid(pkt, sizeof(pkt)), PktUnfinished);
}

TEST(PacketTest, WrongChecksum) {
    uint8_t pkt[] = {0xAC, 0x05, 0x00, 0x00, 0x00, 0x02, 0x01, 0xFF, 0x00}; // 0x00 is wrong CS
    EXPECT_EQ(isPacketValid(pkt, sizeof(pkt)), PktInvalid);
}

TEST(PacketTest, PayloadStructSizes) {
    EXPECT_EQ(sizeof(PktHeader), 7);
    EXPECT_EQ(ImuPayloadSize, 10);
    EXPECT_EQ(sizeof(ImuPayload), 10);
    EXPECT_EQ(SetStatePayloadSize, 13);
    EXPECT_EQ(sizeof(SetStatePayload), 13);
}

TEST(PacketTest, Serialization) {
    uint8_t payload[] = {0xFF};
    uint8_t buffer[FRAME_MAX];

    size_t written = pktSerialize(0x05, 0, 0x02, payload, sizeof(payload), buffer, FRAME_MAX);

    uint8_t expected[] = {0xAC, 0x05, 0x00, 0x00, 0x00, 0x02, 0x01, 0xFF, 0x9F};
    EXPECT_EQ(written, 9);
    for(size_t i = 0; i < written; i++) {
        EXPECT_EQ(buffer[i], expected[i]);
    }
    EXPECT_EQ(isPacketValid(buffer, written), PktValid);
}

TEST(PacketTest, MaxFrameSize) {
    uint8_t payload[PAYLOAD_MAX];
    memset(payload, 0xAA, PAYLOAD_MAX);
    uint8_t longPkt[FRAME_MAX];

    size_t written = pktSerialize(0x01, 0, 0x01, payload, sizeof(payload), longPkt, FRAME_MAX);

    EXPECT_EQ(written, FRAME_MAX);
    EXPECT_EQ(isPacketValid(longPkt, FRAME_MAX), PktValid);
    // One byte short should be unfinished
    EXPECT_EQ(isPacketValid(longPkt, FRAME_MAX - 1), PktUnfinished);
}

TEST(PacketTest, pktSend) {
    vector<uint8_t> sentData;

    uint8_t payload[] = {0xAB, 0xCD};
    PktHeader hdr = {0xAC, 0x0010, 0x0000, 0x01, sizeof(payload)};
    comms::pktSend(hdr, payload, sizeof(payload), [&sentData](const uint8_t* data, uint8_t len) {
        sentData.insert(sentData.end(), data, data + len);
    });

    printf("sentData (hex): ");
    for (auto b : sentData) {
        printf("%02X ", b);
    }
    printf("\n");

    // The sent data should be a valid packet with the given header and payload
    EXPECT_EQ(isPacketValid(sentData.data(), sentData.size()), PktValid);
    EXPECT_EQ(sentData[0], 0xAC); // Start byte
    EXPECT_EQ(sentData[1], 0x10); // to
    EXPECT_EQ(sentData[2], 0x00); // to
    EXPECT_EQ(sentData[3], 0x00); // from
    EXPECT_EQ(sentData[4], 0x00); // from
    EXPECT_EQ(sentData[5], 0x01); // Type
    EXPECT_EQ(sentData[6], sizeof(payload)); // Plen
    EXPECT_EQ(sentData[7], 0xAB); // Payload byte 1
    EXPECT_EQ(sentData[8], 0xCD); // Payload byte 2
}
