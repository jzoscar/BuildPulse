#include "pulse/checksum.hpp"

#include <array>
#include <cstddef>

#if defined(_MSC_VER) && (defined(_M_X64) || defined(_M_IX86))
#include <xmmintrin.h>  // _mm_prefetch
#endif

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

// Cache prefetch hint that compiles everywhere: the GCC/Clang builtin works on every target
// (x86, aarch64, ...), MSVC only has the SSE intrinsic on x86/x64. A hint never changes results.
inline void prefetch(const void* address) {
#if defined(__GNUC__) || defined(__clang__)
    __builtin_prefetch(address);
#elif defined(_MSC_VER) && (defined(_M_X64) || defined(_M_IX86))
    _mm_prefetch(static_cast<const char*>(address), _MM_HINT_T0);
#else
    (void)address;
#endif
}

}  // namespace

std::uint32_t crc32(std::string_view data) {
    constexpr std::size_t kPrefetchDistance = 256;  // bytes ahead; one hint per cache line
    std::uint32_t crc = 0xFFFFFFFFU;
    for (std::size_t i = 0; i < data.size(); ++i) {
        // Only form in-range pointers: data() + n past the end is undefined behaviour.
        if ((i & 63U) == 0 && i + kPrefetchDistance < data.size()) {
            prefetch(data.data() + i + kPrefetchDistance);
        }
        const auto byte = static_cast<unsigned char>(data[i]);
        crc = kTable[(crc ^ byte) & 0xFFU] ^ (crc >> 8);
    }
    return crc ^ 0xFFFFFFFFU;
}

}  // namespace pulse
