import json
from pathlib import Path

from buildpulse.cli import main
from buildpulse.commands import triage

LOGS = Path(__file__).parent / "fixtures" / "logs"


def make_run(tmp_path, stage, log_text, command=None, meta=None, project_dir="/ci/work/proj"):
    run = tmp_path / "runs" / "20260101-000000-x"
    (run / "stages").mkdir(parents=True)
    (run / "stages" / f"02-{stage}.log").write_text(log_text)
    report = {
        "run_id": run.name, "kind": "build", "project_dir": project_dir, "ok": False,
        "meta": meta or {"preset": "linux-arm64", "build_type": "Release"},
        "stages": [
            {"name": "configure", "command": ["cmake"], "returncode": 0, "seconds": 1,
             "log": "stages/01-configure.log"},
            {"name": stage, "command": command or ["cmake", "--build"], "returncode": 1,
             "seconds": 2, "log": f"stages/02-{stage}.log"},
        ],
    }
    (run / "report.json").write_text(json.dumps(report))
    return run / "report.json"


def test_compile_error_from_ci_paths_is_mapped_to_local_source(tmp_path):
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "checksum.cpp").write_text("\n".join(f"line {n}" for n in range(1, 21)))
    log = ("FAILED: x.o\n/home/runner/work/proj/src/checksum.cpp:14:12: "
           "error: 'crc_table' was not declared in this scope\n")
    t = triage.build(make_run(tmp_path, "build", log), proj, context=1)

    assert t.category == "compile"
    assert t.failed_stage == "build"
    assert t.sources[0].file == "src/checksum.cpp"
    assert ">   14 | line 14" in t.sources[0].snippet
    assert "   13 | line 13" in t.sources[0].snippet


def test_link_and_docker_wrapper(tmp_path):
    log = (LOGS / "ld_undefined.log").read_text()
    cmd = ["docker", "run", "--rm", "-v", "/a:/a", "img/cross", "cmake", "--build", "x"]
    t = triage.build(make_run(tmp_path, "build", log, cmd, {"docker_image": "img/cross"}), tmp_path)
    assert t.category == "link"
    assert t.command == ["cmake", "--build", "x"]
    assert t.environment["docker_image"] == "img/cross"


def test_failed_tests_are_listed(tmp_path):
    log = ("[  FAILED  ] Crc32.KnownString (0 ms)\n"
           "The following tests FAILED:\n\t  3 - Crc32.KnownString (Failed)\n")
    t = triage.build(make_run(tmp_path, "test", log), tmp_path)
    assert t.category == "test"
    assert t.failed_tests == ["Crc32.KnownString"]


def test_dependencies_and_success(tmp_path):
    t = triage.build(make_run(tmp_path, "deps", "ERROR: Package 'gtest/9.9' not resolved\n"),
                     tmp_path)
    assert t.category == "dependencies"

    ok_run = tmp_path / "ok"
    ok_run.mkdir()
    (ok_run / "report.json").write_text(json.dumps({"run_id": "ok", "stages": [
        {"name": "build", "command": [], "returncode": 0, "seconds": 1, "log": "x"}]}))
    assert triage.build(ok_run / "report.json", tmp_path).ok


def test_cli_markdown_and_json(tmp_path, capsys):
    make_run(tmp_path, "build", (LOGS / "msvc_c2065.log").read_text())
    logs = str(tmp_path / "runs")
    (tmp_path / "runs" / "latest.txt").write_text("20260101-000000-x")
    assert main(["triage", "--log-dir", logs, "-C", str(tmp_path)]) == 0
    md = capsys.readouterr().out
    assert "**Category:** compile" in md and "[C2065]" in md
    assert main(["triage", "--json", "--log-dir", logs, "-C", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["diagnostics"][0]["code"] == "C2065"
