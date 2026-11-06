# Cross-compilation image: x86_64 Linux host -> aarch64 Linux target.
#
#   compiler   Debian GCC 12 cross toolchain (aarch64-linux-gnu-*)
#   sysroot    /opt/sysroot/aarch64-linux-gnu, built from Debian bookworm arm64 packages,
#              i.e. the same glibc/libstdc++ as Raspberry Pi OS (bookworm) on the device
#   toolchain  /opt/buildpulse/toolchains/aarch64-linux-gnu.cmake (also set as the default
#              via CMAKE_TOOLCHAIN_FILE, so any CMake project cross-compiles unchanged)
#   emulator   qemu-aarch64, so ctest / gtest_discover_tests can run target binaries
#
# Build:  docker build -t buildpulse/cross-arm64 -f docker/cross-arm64.Dockerfile .

FROM --platform=linux/amd64 debian:bookworm-slim

ARG GCC_VERSION=12
# Extra arm64 -dev packages to put in the sysroot (libraries your project links against).
ARG SYSROOT_EXTRA_PACKAGES=""

ENV SYSROOT=/opt/sysroot/aarch64-linux-gnu

RUN dpkg --add-architecture arm64 \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      g++-${GCC_VERSION}-aarch64-linux-gnu gcc-${GCC_VERSION}-aarch64-linux-gnu \
      binutils-aarch64-linux-gnu cmake ninja-build make qemu-user ca-certificates file \
 && mkdir -p /tmp/debs "${SYSROOT}" && cd /tmp/debs \
 && apt-get download \
      libc6:arm64 libc6-dev:arm64 linux-libc-dev:arm64 libcrypt1:arm64 libcrypt-dev:arm64 \
      libgcc-s1:arm64 libgcc-${GCC_VERSION}-dev:arm64 \
      libstdc++6:arm64 libstdc++-${GCC_VERSION}-dev:arm64 \
      ${SYSROOT_EXTRA_PACKAGES} \
 && for deb in *.deb; do dpkg-deb -x "$deb" "${SYSROOT}"; done \
 && cd / && rm -rf /tmp/debs /var/lib/apt/lists/* \
 && for tool in gcc g++; do \
      ln -sf "/usr/bin/aarch64-linux-gnu-${tool}-${GCC_VERSION}" "/usr/local/bin/aarch64-linux-gnu-${tool}"; \
    done

COPY toolchains/aarch64-linux-gnu.cmake /opt/buildpulse/toolchains/aarch64-linux-gnu.cmake
ENV CMAKE_TOOLCHAIN_FILE=/opt/buildpulse/toolchains/aarch64-linux-gnu.cmake
