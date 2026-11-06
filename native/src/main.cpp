#include <cstdio>
#include <iostream>
#include <iterator>
#include <string>

#include "pulse/checksum.hpp"

// Usage: pulse <text>   or   echo -n text | pulse
int main(int argc, char** argv) {
    std::string input;
    if (argc > 1) {
        input = argv[1];
    } else {
        input.assign(std::istreambuf_iterator<char>(std::cin), {});
    }
    std::printf("%08x\n", static_cast<unsigned>(pulse::crc32(input)));
    return 0;
}
