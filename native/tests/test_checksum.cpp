#include <gtest/gtest.h>

#include <string>

#include "pulse/checksum.hpp"

TEST(Crc32, EmptyInput) { EXPECT_EQ(pulse::crc32(""), 0x00000000U); }

TEST(Crc32, StandardCheckValue) {
    // The canonical CRC-32 check value for "123456789".
    EXPECT_EQ(pulse::crc32("123456789"), 0xCBF43926U);
}

TEST(Crc32, KnownString) {
    EXPECT_EQ(pulse::crc32("The quick brown fox jumps over the lazy dog"), 0x414FA339U);
}

TEST(Crc32, LargeInputCrossesPrefetchDistance) {
    // Exercises the prefetching loop well past its look-ahead distance.
    // Reference value: Python's zlib.crc32(b"a" * 4096).
    const std::string data(4096, 'a');
    EXPECT_EQ(pulse::crc32(data), 0x9C99DC73U);
}
