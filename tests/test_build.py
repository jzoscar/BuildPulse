import json
from pathlib import Path

from buildpulse.commands import build

PROJ = Path("/src/proj")


def test_preset_plan_includes_test_stage_by_default():
    stages = build.plan(PROJ, "host-debug")
    assert [name for name, _ in stages] == ["configure", "build", "test"]
    assert stages[0][1] == ["cmake", "--preset", "host-debug"]


def test_plan_without_tests():
    names = [name for name, _ in build.plan(PROJ, "host-debug", run_tests=False)]
    assert names == ["configure", "build"]


def test_plain_plan_uses_explicit_source_and_build_dirs():
    stages = dict(build.plan(PROJ, None, build_type="Release"))
    assert stages["configure"] == [
        "cmake", "-S", "/src/proj", "-B", "/src/proj/build/buildpulse",
        "-DCMAKE_BUILD_TYPE=Release",
    ]
    assert stages["test"][:3] == ["ctest", "--test-dir", "/src/proj/build/buildpulse"]


def test_clean_reconfigures_fresh_and_rebuilds():
    stages = dict(build.plan(PROJ, "host-debug", clean=True))
    assert stages["configure"][-1] == "--fresh"
    assert stages["build"][-1] == "--clean-first"


def test_validate(tmp_path):
    assert "no CMakeLists.txt" in build.validate(tmp_path, None)
    (tmp_path / "CMakeLists.txt").write_text("")
    assert build.validate(tmp_path, None) is None
    assert "no CMakePresets.json" in build.validate(tmp_path, "x")


def test_run_stops_at_first_failure_and_records_it(tmp_path, monkeypatch):
    def fake_plan(*args, **kwargs):
        return [("configure", ["true"]), ("build", ["false"]), ("test", ["true"])]

    monkeypatch.setattr(build, "plan", fake_plan)
    report = build.run(tmp_path, tmp_path / "logs", preset="p", echo=False)

    assert not report.ok
    assert [s.name for s in report.stages] == ["configure", "build"]
    data = json.loads((Path(report.run_dir) / "report.json").read_text())
    assert data["ok"] is False
    assert data["exit_code"] == 1
    assert data["meta"]["mode"] == "preset"
