#include "pulse/checksum.hpp"

#include <array>
#include <cstddef>

#include <xmmintrin.h>  // _mm_prefetch

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
    constexpr std::size_t kPrefetchDistance = 256;  // bytes ahead; one hint per cache line
    std::uint32_t crc = 0xFFFFFFFFU;
    for (std::size_t i = 0; i < data.size(); ++i) {
        if ((i & 63U) == 0) {
            _mm_prefetch(data.data() + i + kPrefetchDistance, _MM_HINT_T0);
        }
        const auto byte = static_cast<unsigned char>(data[i]);
        crc = kTable[(crc ^ byte) & 0xFFU] ^ (crc >> 8);
    }
    return crc ^ 0xFFFFFFFFU;
}

}  // namespace pulse
