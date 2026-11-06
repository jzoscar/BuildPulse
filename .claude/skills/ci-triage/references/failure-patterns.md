# Failure patterns on BuildPulse toolchains

Team knowledge for the `ci-triage` skill: what fails where, and the fix that holds up.
Add a row whenever a triage teaches you something new.

## Toolchains

| Job | Compiler | Target | Notes |
|---|---|---|---|
| `ci` / native-linux-x64 | GCC (Ubuntu runner) | x86_64 Linux | `-Wall -Wextra -Wpedantic` |
| `cross-arm64` | GCC 12 cross (`aarch64-linux-gnu-g++`) | aarch64 Linux, Debian bookworm sysroot (glibc 2.36) | Tests run under `qemu-aarch64` |
| `windows-msvc` | MSVC 19.5x (`cl.exe`), Ninja | x86_64 Windows | `/W4 /permissive-`, sccache |
| local `host-debug` | Apple clang | arm64 macOS | Not in CI |

## Patterns

| Symptom | Where | Root cause | Fix |
|---|---|---|---|
| `xmmintrin.h` / `nmmintrin.h` / `immintrin.h`: No such file; `__builtin_ia32_*` undeclared; `_mm_crc32_u8` undeclared | aarch64 cross, Apple silicon | x86 SSE/AVX intrinsics used without an architecture guard | Guard with `#if defined(__x86_64__) \|\| defined(_M_X64)` (and `__SSE4_2__` / `__AVX2__` or a runtime CPU check); keep a portable fallback; optionally add the aarch64 equivalent (`<arm_acle.h>`, `__crc32b` with `-march=armv8-a+crc`) |
| `__builtin_*` / `__attribute__` unknown, `C2065`, `C3861` | MSVC only | GCC/Clang extension | Use the standard facility (`<bit>`, `std::popcount`) or an `#ifdef _MSC_VER` branch |
| `C4244` / `C4267` conversion warnings fail the build | MSVC only | Implicit narrowing that GCC does not warn about at our level | Make the conversion explicit with `static_cast` and check the range |
| Undefined reference only on Linux | GCC, both arches | Symbol defined in a file excluded by a platform `if()` in CMake, or link order | Fix the target's sources / `target_link_libraries` |
| `cannot find -l<lib>` / `Could NOT find <Pkg>` | aarch64 cross | Library not in the sysroot | Add its `:arm64` `-dev` package via `SYSROOT_EXTRA_PACKAGES` or as a Conan dependency; never point at host libraries |
| `GLIBC_2.3x not found` on the device | Runtime on device | Built against a newer glibc than the device has | Keep the sysroot at the device's distro release (bookworm) |
| `ERROR: Missing prebuilt package` / `Missing binary` | `deps` stage | No binary for this profile in the cache or remote | Expected with `--build=missing`: it builds from source. If it fails, check the profile (`compiler.version`, `cppstd`) |
| `Generator Ninja does not support platform specification` | Windows `configure` | Conan toolchain written for the Visual Studio generator | Pin `tools.cmake.cmaketoolchain:generator` to the preset's generator (buildpulse does this) |
| Test passes natively, fails under QEMU | aarch64 test | Real arch difference (`char` signedness, alignment, endianness assumptions) far more often than a QEMU bug | Fix the assumption (`unsigned char`, `memcpy` instead of type punning) |
| `_mm_prefetch` for a "perf" change breaks aarch64 (seen in #1) | aarch64 cross | SSE prefetch intrinsic | `__builtin_prefetch` on GCC/Clang (all arches), `_mm_prefetch` only under `_MSC_VER` + `_M_X64`; only form in-range pointers (`p + n` past one-past-the-end is UB) |
| Test asserts `src/x.cpp`, gets `src\x.cpp` (seen in #2) | Windows, buildpulse's own pytest | `str(Path)` uses `\` on Windows | Use `.as_posix()` for paths shown to people/agents or compared with log text |
| Different numeric result per platform | Tests | `long` is 32-bit on Windows, 64-bit on Linux; floating-point contraction | Use fixed-width types (`std::uint32_t`), tolerances for floats |
