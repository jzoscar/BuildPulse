import json
import subprocess

from buildpulse.commands import build


def test_plan_includes_test_stage_by_default():
    names = [name for name, _ in build.plan("host-debug", run_tests=True)]
    assert names == ["configure", "build", "test"]


def test_plan_without_tests():
    names = [name for name, _ in build.plan("host-debug", run_tests=False)]
    assert names == ["configure", "build"]


def test_run_stops_at_first_failure_and_writes_report(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, check, cwd):
        calls.append(cmd)
        rc = 1 if cmd[:2] == ["cmake", "--build"] else 0
        return subprocess.CompletedProcess(cmd, rc)

    monkeypatch.setattr(build.subprocess, "run", fake_run)
    report = build.run(tmp_path, "host-debug")

    assert not report.ok
    assert [s.name for s in report.stages] == ["configure", "build"]
    assert len(calls) == 2
    data = json.loads((tmp_path / "build" / "host-debug" / "buildpulse-report.json").read_text())
    assert data["ok"] is False
    assert data["stages"][1]["returncode"] == 1
