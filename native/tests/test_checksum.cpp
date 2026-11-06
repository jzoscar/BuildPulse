#include <gtest/gtest.h>

#include "pulse/checksum.hpp"

TEST(Crc32, EmptyInput) { EXPECT_EQ(pulse::crc32(""), 0x00000000U); }

TEST(Crc32, StandardCheckValue) {
    // The canonical CRC-32 check value for "123456789".
    EXPECT_EQ(pulse::crc32("123456789"), 0xCBF43926U);
}

TEST(Crc32, KnownString) {
    EXPECT_EQ(pulse::crc32("The quick brown fox jumps over the lazy dog"), 0x414FA339U);
}
