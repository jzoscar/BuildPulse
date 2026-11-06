from conan import ConanFile
from conan.tools.cmake import CMakeDeps, CMakeToolchain


class PulseConan(ConanFile):
    settings = "os", "arch", "compiler", "build_type"

    def requirements(self):
        self.test_requires("gtest/1.15.0")

    def generate(self):
        tc = CMakeToolchain(self)
        tc.user_presets_path = False  # don't write CMakeUserPresets.json into the source tree
        tc.generate()
        CMakeDeps(self).generate()
