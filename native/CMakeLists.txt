cmake_minimum_required(VERSION 3.23)
# MSVC: put debug info in the object files (/Z7) instead of a shared PDB (/Zi) so that
# sccache/ccache can cache them. Needs policy CMP0141 (CMake >= 3.25).
if(POLICY CMP0141)
  cmake_policy(SET CMP0141 NEW)
  set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "$<$<CONFIG:Debug,RelWithDebInfo>:Embedded>")
endif()
project(pulse VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

option(PULSE_BUILD_TESTS "Build GTest unit tests" ON)

if(MSVC)
  set(PULSE_WARNINGS /W4 /permissive-)
else()
  set(PULSE_WARNINGS -Wall -Wextra -Wpedantic)
endif()

add_library(pulse_core src/checksum.cpp)
target_include_directories(pulse_core PUBLIC include)
target_compile_options(pulse_core PRIVATE ${PULSE_WARNINGS})

add_executable(pulse src/main.cpp)
target_link_libraries(pulse PRIVATE pulse_core)
target_compile_options(pulse PRIVATE ${PULSE_WARNINGS})

if(PULSE_BUILD_TESTS)
  enable_testing()
  # Prefer a prebuilt GTest (from Conan, see conanfile.py); fall back to building it from source.
  find_package(GTest CONFIG QUIET)
  if(GTest_FOUND)
    message(STATUS "GTest: using package from ${GTest_DIR}")
  else()
    message(STATUS "GTest: not found as a package, fetching and building from source")
    include(FetchContent)
    FetchContent_Declare(
      googletest
      URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.tar.gz
      DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    )
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
  endif()

  add_executable(pulse_tests tests/test_checksum.cpp)
  target_link_libraries(pulse_tests PRIVATE pulse_core GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(pulse_tests)
endif()
