# CMake toolchain file: cross-compile for 64-bit Arm Linux (aarch64) with GCC.
#
# Expects aarch64-linux-gnu-gcc/g++ on PATH and a target sysroot in $SYSROOT
# (default /opt/sysroot/aarch64-linux-gnu), as provided by docker/cross-arm64.Dockerfile.

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)

if(DEFINED ENV{SYSROOT})
  set(CMAKE_SYSROOT "$ENV{SYSROOT}")
else()
  set(CMAKE_SYSROOT /opt/sysroot/aarch64-linux-gnu)
endif()

# Look for headers/libraries/packages only in the sysroot, programs only on the host.
set(CMAKE_FIND_ROOT_PATH "${CMAKE_SYSROOT}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

# Run target binaries (ctest, gtest_discover_tests) under user-mode QEMU.
find_program(QEMU_AARCH64 qemu-aarch64)
if(QEMU_AARCH64)
  set(CMAKE_CROSSCOMPILING_EMULATOR "${QEMU_AARCH64};-L;${CMAKE_SYSROOT}")
endif()
