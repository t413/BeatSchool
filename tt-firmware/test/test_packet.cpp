#include <gtest/gtest.h>
#include <vector>
#include <Packet.h>

using namespace std;
using namespace comms;

TEST(PacketTest, Checksum) {
    uint8_t data[] = {0xAC, 0x01, 0x02, 0x03};
    uint8_t expected = 0xAC ^ 0x01 ^ 0x02 ^ 0x03;
    EXPECT_EQ(checksum(data, 4), expected);
}

TEST(PacketTest, ValidPacket) {
    // Header: Start(0xAC), ID(0x05), Type(0x02), Plen(0x01)
    // Payload: 0xFF
    // Checksum: AC ^ 05 ^ 02 ^ 01 ^ FF = 0x55
    uint8_t pkt[] = {0xAC, 0x05, 0x02, 0x01, 0xFF, 0x55};
    EXPECT_EQ(isPacketValid(pkt, sizeof(pkt)), PktValid);
}

TEST(PacketTest, InvalidStartByte) {
    uint8_t pkt[] = {0xFF, 0x05, 0x02, 0x01, 0xFF, 0x55};
    EXPECT_EQ(isPacketValid(pkt, sizeof(pkt)), PktInvalid);
}

TEST(PacketTest, UnfinishedPacket) {
    uint8_t pkt[] = {0xAC, 0x05, 0x02, 0x01}; // Missing payload and checksum
    EXPECT_EQ(isPacketValid(pkt, sizeof(pkt)), PktUnfinished);
}

TEST(PacketTest, WrongChecksum) {
    uint8_t pkt[] = {0xAC, 0x05, 0x02, 0x01, 0xFF, 0x00}; // 0x00 is wrong CS
    EXPECT_EQ(isPacketValid(pkt, sizeof(pkt)), PktInvalid);
}

TEST(PacketTest, PayloadStructSizes) {
    EXPECT_EQ(sizeof(PktHeader), 4);
    EXPECT_EQ(ImuPayloadSize, 14);
    EXPECT_EQ(sizeof(ImuPayload), 14);
    EXPECT_EQ(SetStatePayloadSize, 6);
    EXPECT_EQ(sizeof(SetStatePayload), 6);
}

TEST(PacketTest, Serialization) {
    uint8_t payload[] = {0xFF};
    uint8_t buffer[FRAME_MAX];

    size_t written = pktSerialize(0x05, 0x02, payload, sizeof(payload), buffer, FRAME_MAX);

    uint8_t expected[] = {0xAC, 0x05, 0x02, 0x01, 0xFF, 0x55};
    EXPECT_EQ(written, 6);
    for(size_t i = 0; i < written; i++) {
        EXPECT_EQ(buffer[i], expected[i]);
    }
    EXPECT_EQ(isPacketValid(buffer, written), PktValid);
}

TEST(PacketTest, MaxFrameSize) {
    uint8_t payload[PAYLOAD_MAX];
    memset(payload, 0xAA, PAYLOAD_MAX);
    uint8_t longPkt[FRAME_MAX];

    size_t written = pktSerialize(0x01, 0x01, payload, sizeof(payload), longPkt, FRAME_MAX);

    EXPECT_EQ(written, FRAME_MAX);
    EXPECT_EQ(isPacketValid(longPkt, FRAME_MAX), PktValid);
    // One byte short should be unfinished
    EXPECT_EQ(isPacketValid(longPkt, FRAME_MAX - 1), PktUnfinished);
}
