"""Build any CMake project through configure -> build -> test, recording every stage.

Two modes:
  preset  `cmake --preset X` etc. — used when a preset is given (flag or buildpulse.toml)
  plain   `cmake -S <project> -B <build-dir>` — for projects without CMakePresets.json
"""

from __future__ import annotations

from pathlib import Path

from buildpulse import container
from buildpulse.runner import Recorder, RunReport

DEFAULT_BUILD_DIR = "build/buildpulse"


def plan(
    project_dir: Path,
    preset: str | None,
    build_type: str = "Debug",
    build_dir: Path | None = None,
    run_tests: bool = True,
    clean: bool = False,
) -> list[tuple[str, list[str]]]:
    """Return the (stage name, command) pairs to run from `project_dir`, in order."""
    if preset:
        configure = ["cmake", "--preset", preset]
        build = ["cmake", "--build", "--preset", preset]
        test = ["ctest", "--preset", preset]
    else:
        build_dir = build_dir or project_dir / DEFAULT_BUILD_DIR
        configure = ["cmake", "-S", str(project_dir), "-B", str(build_dir),
                     f"-DCMAKE_BUILD_TYPE={build_type}"]
        build = ["cmake", "--build", str(build_dir), "--parallel"]
        test = ["ctest", "--test-dir", str(build_dir), "--output-on-failure"]
    if clean:
        configure.append("--fresh")
        build.append("--clean-first")

    stages = [("configure", configure), ("build", build)]
    if run_tests:
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
    project_dir: Path,
    log_dir: Path,
    preset: str | None = None,
    build_type: str = "Debug",
    build_dir: Path | None = None,
    run_tests: bool = True,
    clean: bool = False,
    docker_image: str | None = None,
    echo: bool = True,
) -> RunReport:
    label = preset or f"plain-{build_type.lower()}"
    recorder = Recorder(log_dir, kind="build", label=label, project_dir=project_dir, echo=echo)
    mounts = [project_dir] + ([build_dir] if build_dir else [])
    platform = container.image_platform(docker_image) if docker_image else None
    for name, cmd in plan(project_dir, preset, build_type, build_dir, run_tests, clean):
        if docker_image:
            cmd = container.wrap(cmd, docker_image, project_dir, mounts, platform)
        if recorder.stage(name, cmd, cwd=project_dir).returncode != 0:
            break
    return recorder.finish(
        mode="preset" if preset else "plain",
        docker_image=docker_image,
        preset=preset,
        build_type=None if preset else build_type,
        build_dir=None if preset else str(build_dir or project_dir / DEFAULT_BUILD_DIR),
    )
