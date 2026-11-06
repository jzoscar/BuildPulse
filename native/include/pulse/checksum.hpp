#pragma once

#include <cstdint>
#include <string_view>

namespace pulse {

// CRC-32 (IEEE 802.3, reflected, poly 0xEDB88320) — same as zlib's crc32().
std::uint32_t crc32(std::string_view data);

}  // namespace pulse
