#include "pulse/checksum.hpp"

#include <array>

namespace pulse {
namespace {

constexpr std::array<std::uint32_t, 256> make_table() {
    std::array<std::uint32_t, 256> table{};
    for (std::uint32_t i = 0; i < 256; ++i) {
        std::uint32_t c = i;
        for (int k = 0; k < 8; ++k) {
            c = (c & 1U) ? 0xEDB88320U ^ (c >> 1) : c >> 1;
        }
        table[i] = c;
    }
    return table;
}

constexpr auto kTable = make_table();

}  // namespace

std::uint32_t crc32(std::string_view data) {
    std::uint32_t crc = 0xFFFFFFFFU;
    for (unsigned char byte : data) {
        crc = kTable[(crc ^ byte) & 0xFFU] ^ (crc >> 8);
    }
    return crc ^ 0xFFFFFFFFU;
}

}  // namespace pulse
