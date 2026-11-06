"""Build any CMake project through deps -> configure -> build -> test, recording every stage.

Two CMake modes:
  preset  `cmake --preset X` etc. — used when a preset is given (flag or buildpulse.toml)
  plain   `cmake -S <project> -B <build-dir>` — for projects without CMakePresets.json

If the project has a conanfile.py/conanfile.txt, a `deps` stage runs `conan install` first and
the configure stage uses the generated conan_toolchain.cmake. With caching on, ccache or sccache
is set as the compiler launcher and its hit rate is recorded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from buildpulse import cache, container
from buildpulse.runner import Recorder, RunReport

DEFAULT_BUILD_DIR = "build/buildpulse"
CONANFILES = ("conanfile.py", "conanfile.txt")


@dataclass
class BuildOptions:
    project_dir: Path
    preset: str | None = None
    build_type: str = "Debug"
    build_dir: Path | None = None
    run_tests: bool = True
    clean: bool = False
    deps: str = "auto"  # auto | conan | none
    caches: cache.CacheSettings | None = None
    in_docker: bool = False

    @property
    def label(self) -> str:
        return self.preset or f"plain-{self.build_type.lower()}"

    @property
    def uses_conan(self) -> bool:
        if self.deps == "none":
            return False
        return self.deps == "conan" or any((self.project_dir / f).is_file() for f in CONANFILES)

    @property
    def conan_output(self) -> Path:
        return self.project_dir / "build" / "conan" / self.label

    @property
    def effective_build_type(self) -> str:
        if self.preset:
            return preset_build_type(self.project_dir, self.preset) or "Release"
        return self.build_type


def _preset_lookup(project_dir: Path, preset: str, get) -> str | None:
    """First non-empty `get(preset_dict)` along a configure preset's `inherits` chain."""
    try:
        data = json.loads((project_dir / "CMakePresets.json").read_text())
    except (OSError, ValueError):
        return None
    presets = {p["name"]: p for p in data.get("configurePresets", [])}
    pending = [preset]
    while pending:
        current = presets.get(pending.pop(0), {})
        value = get(current)
        if value:
            return value["value"] if isinstance(value, dict) else value
        inherits = current.get("inherits", [])
        pending.extend([inherits] if isinstance(inherits, str) else inherits)
    return None


def preset_build_type(project_dir: Path, preset: str) -> str | None:
    """CMAKE_BUILD_TYPE of a configure preset, following `inherits`."""
    return _preset_lookup(
        project_dir, preset, lambda p: p.get("cacheVariables", {}).get("CMAKE_BUILD_TYPE"))


def preset_generator(project_dir: Path, preset: str) -> str | None:
    """CMake generator of a configure preset, following `inherits`."""
    return _preset_lookup(project_dir, preset, lambda p: p.get("generator"))


def plan(opts: BuildOptions) -> list[tuple[str, list[str]]]:
    """Return the (stage name, command) pairs to run from `opts.project_dir`, in order."""
    stages: list[tuple[str, list[str]]] = []

    if opts.uses_conan:
        if not opts.in_docker:
            # Images provide their profiles via CONAN_DEFAULT_PROFILE/CONAN_DEFAULT_BUILD_PROFILE.
            stages.append(("conan-profile", ["conan", "profile", "detect", "--exist-ok"]))
        conan_build = opts.caches.conan_build if opts.caches else "missing"
        stages.append(("deps", [
            "conan", "install", str(opts.project_dir),
            "--output-folder", str(opts.conan_output),
            f"--build={conan_build}",
            "-s", f"build_type={opts.effective_build_type}",
        ]))
        lockfile = opts.project_dir / "conan.lock"
        if lockfile.is_file():
            # Pinned dependency revisions: reproducible builds, and the SBOM matches the build.
            stages[-1][1].extend(["--lockfile", str(lockfile)])
        generator = preset_generator(opts.project_dir, opts.preset) if opts.preset else None
        if generator:
            # conan_toolchain.cmake must match the generator, e.g. no VS platform/toolset
            # settings when MSVC builds use Ninja.
            stages[-1][1].extend(["-c", f"tools.cmake.cmaketoolchain:generator={generator}"])

    if opts.preset:
        configure = ["cmake", "--preset", opts.preset]
        build = ["cmake", "--build", "--preset", opts.preset]
        test = ["ctest", "--preset", opts.preset]
    else:
        build_dir = opts.build_dir or opts.project_dir / DEFAULT_BUILD_DIR
        configure = ["cmake", "-S", str(opts.project_dir), "-B", str(build_dir),
                     f"-DCMAKE_BUILD_TYPE={opts.build_type}"]
        build = ["cmake", "--build", str(build_dir), "--parallel"]
        test = ["ctest", "--test-dir", str(build_dir), "--output-on-failure"]

    if opts.uses_conan:
        toolchain = (opts.conan_output / "conan_toolchain.cmake").as_posix()
        configure.append(f"-DCMAKE_TOOLCHAIN_FILE={toolchain}")
    tool = opts.caches.compiler_cache if opts.caches else None
    if opts.caches is not None:
        # Always explicit, so turning the cache off also takes effect in an existing build tree.
        launcher = tool or ""
        configure += [f"-DCMAKE_C_COMPILER_LAUNCHER={launcher}",
                      f"-DCMAKE_CXX_COMPILER_LAUNCHER={launcher}"]
    if opts.clean:
        configure.append("--fresh")
        build.append("--clean-first")

    stages.append(("configure", configure))
    if tool:
        stages.append(("cache-zero", [tool, "--zero-stats"]))
    stages.append(("build", build))
    if tool:
        stages.append(("cache-stats", [tool, "--show-stats"]))
    if opts.run_tests:
        stages.append(("test", test))
    return stages


def validate(project_dir: Path, preset: str | None) -> str | None:
    """Return an error message if `project_dir` cannot be built, else None."""
    if not (project_dir / "CMakeLists.txt").is_file():
        return f"{project_dir} has no CMakeLists.txt"
    if preset and not (project_dir / "CMakePresets.json").is_file():
        return f"--preset {preset} given but {project_dir} has no CMakePresets.json"
    return None


def run(
    opts: BuildOptions, log_dir: Path, docker_image: str | None = None, echo: bool = True
) -> RunReport:
    opts.in_docker = docker_image is not None
    env = opts.caches.env if opts.caches else {}
    recorder = Recorder(
        log_dir, kind="build", label=opts.label, project_dir=opts.project_dir, echo=echo
    )
    mounts = [opts.project_dir, *([opts.build_dir] if opts.build_dir else []),
              *(opts.caches.mounts if opts.caches else [])]
    platform = container.image_platform(docker_image) if docker_image else None

    cache_stats = None
    for name, cmd in plan(opts):
        if docker_image:
            cmd = container.wrap(cmd, docker_image, opts.project_dir, mounts, platform, env)
        stage = recorder.stage(name, cmd, cwd=opts.project_dir, env=env)
        if name == "cache-stats" and opts.caches and opts.caches.compiler_cache:
            output = (recorder.run_dir / stage.log).read_text(errors="replace")
            cache_stats = cache.parse_stats(opts.caches.compiler_cache, output)
        if stage.returncode != 0:
            break

    return recorder.finish(
        mode="preset" if opts.preset else "plain",
        docker_image=docker_image,
        preset=opts.preset,
        build_type=opts.effective_build_type,
        build_dir=None if opts.preset else str(
            opts.build_dir or opts.project_dir / DEFAULT_BUILD_DIR
        ),
        deps="conan" if opts.uses_conan else "none",
        cache=opts.caches.describe() if opts.caches else None,
        compiler_cache_stats=cache_stats,
        clean=opts.clean,
    )
