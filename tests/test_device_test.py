import json
import sys
from pathlib import Path

import pytest

from buildpulse.commands import device_test, triage

# Stands in for the labforge CLI: records every call, fails the command named in FAKE_FAIL.
FAKE_LABFORGE = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(args) + "\n")
cmd = args[1]
if os.environ.get("FAKE_FAIL") == cmd:
    print(f"error 409: {cmd} failed", file=sys.stderr)
    sys.exit(2 if cmd == "checkout" else 1)
if cmd == "checkout":
    lease = {"leaseId": 7, "device": "sim-sensor-02", "address": "sim-lab.host.sim-sensor-02",
             "host": "127.0.0.1", "endpoints": {"http": "http://127.0.0.1:9121"},
             "platform": {"os": "linux", "arch": "arm64"}, "labels": {"pool": "sim-sensor"}}
    open(args[args.index("--write") + 1], "w").write(json.dumps(lease))
print(cmd, "ok")
'''


@pytest.fixture
def device_run(tmp_path, monkeypatch):
    script = tmp_path / "labforge.py"
    script.write_text(FAKE_LABFORGE)
    calls = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CALLS", str(calls))
    firmware = tmp_path / "pulse"
    firmware.write_bytes(b"\x7fELF aarch64 build")

    def run(fail=None, test_cmd=None):
        if fail:
            monkeypatch.setenv("FAKE_FAIL", fail)
        report = device_test.run("sim-sensor", firmware, "1.2.3-g30acdbb", tmp_path / "runs",
                                 holder="ci#1", test_cmd=test_cmd, project_dir=tmp_path,
                                 labforge=[sys.executable, str(script)], echo=False)
        made = [json.loads(line) for line in calls.read_text().splitlines()]
        return report, made

    run.firmware = firmware
    return run


def _triage(report):
    return triage.build(Path(report.run_dir) / "report.json", Path("."))


def test_passing_device_test_flashes_verifies_and_releases(device_run):
    check_env = [sys.executable, "-c", "import os; assert os.environ['LABFORGE_DEVICE_HTTP']"]
    report, calls = device_run(test_cmd=check_env)
    assert report.ok
    assert [s.name for s in report.stages] == ["checkout", "flash", "verify", "test", "release"]
    assert [c[1] for c in calls] == ["checkout", "flash", "check", "release"]
    assert calls[1][2] == "7" and str(device_run.firmware) in calls[1]
    assert calls[-1][-2:] == ["--result", "passed"]
    assert report.meta["result"] == "passed" and report.meta["device"]["device"] == "sim-sensor-02"
    assert report.meta["firmware"]["sha256"] == device_test.sha256(device_run.firmware)


def test_failed_test_is_a_code_failure_and_the_device_goes_back(device_run):
    report, calls = device_run(test_cmd=[sys.executable, "-c", "raise SystemExit(3)"])
    assert not report.ok and report.exit_code == 3 and report.meta["result"] == "failed"
    assert calls[-1][-2:] == ["--result", "failed"]
    t = _triage(report)
    assert t.category == "test" and t.failed_stage == "test"
    assert t.environment["device"] == "sim-sensor-02" and t.environment["firmware"] == "1.2.3-g30acdbb"


def test_flash_failure_is_infrastructure(device_run):
    report, calls = device_run(fail="flash")
    assert [s.name for s in report.stages] == ["checkout", "flash", "release"]
    assert report.meta["result"] == "infra-failed" and calls[-1][-2:] == ["--result", "infra-failed"]
    t = _triage(report)
    assert t.category == "infrastructure" and t.failed_stage == "flash"


def test_no_device_available_stops_after_checkout(device_run):
    report, calls = device_run(fail="checkout")
    assert [c[1] for c in calls] == ["checkout"] and [s.name for s in report.stages] == ["checkout"]
    assert report.exit_code == 2 and report.meta["result"] == "infra-failed"
    assert _triage(report).category == "infrastructure"
