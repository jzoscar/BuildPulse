cmake_minimum_required(VERSION 3.23)
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
  # Temporary: fetched from source. Will move to Conan with binary caching later.
  include(FetchContent)
  FetchContent_Declare(
    googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
  )
  set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)

  add_executable(pulse_tests tests/test_checksum.cpp)
  target_link_libraries(pulse_tests PRIVATE pulse_core GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(pulse_tests)
endif()
