import json
from pathlib import Path

from buildpulse import cache
from buildpulse.commands import build

PROJ = Path("/src/proj")


def names(stages):
    return [name for name, _ in stages]


def caches(conan_cache=True, ccache=True):
    return cache.CacheSettings(
        conan_home=Path("/c/conan2/host"),
        conan_build="missing" if conan_cache else "*",
        conan_cached=conan_cache,
        ccache=ccache,
        ccache_dir=Path("/c/ccache/host") if ccache else None,
    )


def test_preset_plan_includes_test_stage_by_default():
    stages = build.plan(build.BuildOptions(PROJ, preset="host-debug"))
    assert names(stages) == ["configure", "build", "test"]
    assert stages[0][1] == ["cmake", "--preset", "host-debug"]


def test_plan_without_tests():
    opts = build.BuildOptions(PROJ, preset="host-debug", run_tests=False)
    assert names(build.plan(opts)) == ["configure", "build"]


def test_plain_plan_uses_explicit_source_and_build_dirs():
    stages = dict(build.plan(build.BuildOptions(PROJ, build_type="Release")))
    assert stages["configure"] == [
        "cmake", "-S", "/src/proj", "-B", "/src/proj/build/buildpulse",
        "-DCMAKE_BUILD_TYPE=Release",
    ]
    assert stages["test"][:3] == ["ctest", "--test-dir", "/src/proj/build/buildpulse"]


def test_clean_reconfigures_fresh_and_rebuilds():
    stages = dict(build.plan(build.BuildOptions(PROJ, preset="host-debug", clean=True)))
    assert stages["configure"][-1] == "--fresh"
    assert stages["build"][-1] == "--clean-first"


def test_conan_project_gets_deps_stage_and_toolchain(tmp_path):
    (tmp_path / "conanfile.py").write_text("")
    opts = build.BuildOptions(tmp_path, build_type="Release", caches=caches())
    stages = dict(build.plan(opts))
    assert list(stages) == [
        "conan-profile", "deps", "configure", "ccache-zero", "build", "ccache-stats", "test",
    ]
    assert "--build=missing" in stages["deps"]
    assert "build_type=Release" in stages["deps"]
    toolchain = tmp_path / "build" / "conan" / "plain-release" / "conan_toolchain.cmake"
    assert f"-DCMAKE_TOOLCHAIN_FILE={toolchain}" in stages["configure"]
    assert "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache" in stages["configure"]


def test_cold_cache_rebuilds_deps_and_disables_ccache(tmp_path):
    (tmp_path / "conanfile.txt").write_text("")
    opts = build.BuildOptions(tmp_path, caches=caches(conan_cache=False, ccache=False))
    stages = dict(build.plan(opts))
    assert "--build=*" in stages["deps"]
    assert "-DCMAKE_CXX_COMPILER_LAUNCHER=" in stages["configure"]
    assert "ccache-zero" not in stages


def test_deps_none_skips_conan_and_docker_skips_profile_detect(tmp_path):
    (tmp_path / "conanfile.py").write_text("")
    assert "deps" not in names(build.plan(build.BuildOptions(tmp_path, deps="none")))
    in_docker = names(build.plan(build.BuildOptions(tmp_path, in_docker=True)))
    assert "deps" in in_docker and "conan-profile" not in in_docker


def test_preset_build_type_follows_inherits(tmp_path):
    (tmp_path / "CMakePresets.json").write_text(json.dumps({"configurePresets": [
        {"name": "base", "cacheVariables": {"CMAKE_BUILD_TYPE": "RelWithDebInfo"}},
        {"name": "child", "inherits": "base"},
    ]}))
    assert build.preset_build_type(tmp_path, "child") == "RelWithDebInfo"
    assert build.preset_build_type(tmp_path, "missing") is None


def test_validate(tmp_path):
    assert "no CMakeLists.txt" in build.validate(tmp_path, None)
    (tmp_path / "CMakeLists.txt").write_text("")
    assert build.validate(tmp_path, None) is None
    assert "no CMakePresets.json" in build.validate(tmp_path, "x")


def test_run_stops_at_first_failure_and_records_it(tmp_path, monkeypatch):
    def fake_plan(opts):
        return [("configure", ["true"]), ("build", ["false"]), ("test", ["true"])]

    monkeypatch.setattr(build, "plan", fake_plan)
    report = build.run(build.BuildOptions(tmp_path, preset="p"), tmp_path / "logs", echo=False)

    assert not report.ok
    assert [s.name for s in report.stages] == ["configure", "build"]
    data = json.loads((Path(report.run_dir) / "report.json").read_text())
    assert data["ok"] is False
    assert data["exit_code"] == 1
    assert data["meta"]["mode"] == "preset"
