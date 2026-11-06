import json
import sys
from pathlib import Path

from buildpulse.cli import main
from buildpulse.runner import Recorder

PY = sys.executable


def test_stage_captures_stdout_and_stderr_to_files(tmp_path):
    rec = Recorder(tmp_path, kind="run", label="demo", project_dir=tmp_path, echo=False)
    code = "import sys; print('to stdout'); print('to stderr', file=sys.stderr); sys.exit(3)"
    stage = rec.stage("compile", [PY, "-c", code], cwd=tmp_path)
    report = rec.finish()

    assert stage.returncode == 3
    assert report.exit_code == 3
    stage_log = (rec.run_dir / stage.log).read_text()
    assert "to stdout" in stage_log and "to stderr" in stage_log
    full_log = (rec.run_dir / "full.log").read_text()
    assert "==> [compile]" in full_log and "<== [compile] exit 3" in full_log


def test_full_log_keeps_stages_in_order(tmp_path):
    rec = Recorder(tmp_path, kind="build", label="x", project_dir=tmp_path, echo=False)
    rec.stage("one", [PY, "-c", "print('first')"], cwd=tmp_path)
    rec.stage("two", [PY, "-c", "print('second')"], cwd=tmp_path)
    rec.finish()

    full = (rec.run_dir / "full.log").read_text()
    assert full.index("first") < full.index("second")
    assert sorted(p.name for p in (rec.run_dir / "stages").iterdir()) == ["01-one.log", "02-two.log"]


def test_missing_command_is_recorded_not_raised(tmp_path):
    rec = Recorder(tmp_path, kind="run", label="x", project_dir=tmp_path, echo=False)
    stage = rec.stage("run", ["definitely-not-a-real-command-xyz"], cwd=tmp_path)
    assert stage.returncode == 127
    assert "cannot start command" in (rec.run_dir / stage.log).read_text()


def test_latest_points_at_newest_run(tmp_path):
    for label in ("a", "b"):
        rec = Recorder(tmp_path, kind="run", label=label, project_dir=tmp_path, echo=False)
        rec.stage("run", [PY, "-c", "pass"], cwd=tmp_path)
        rec.finish()
    assert (tmp_path / "latest").resolve() == rec.run_dir.resolve()


def test_cli_run_custom_script(tmp_path, capsys):
    script = tmp_path / "build.py"
    script.write_text("print('compiling foo.c')\n")
    logs = tmp_path / "logs"

    rc = main(["run", "--log-dir", str(logs), "--cwd", str(tmp_path), "--name", "my-build",
               "--", PY, str(script)])

    assert rc == 0
    report = json.loads((logs / "latest" / "report.json").read_text())
    assert report["kind"] == "run"
    assert report["stages"][0]["name"] == "my-build"
    assert "compiling foo.c" in Path(report["run_dir"], "full.log").read_text()
    assert "log:" in capsys.readouterr().out


def test_cli_run_requires_a_command(capsys):
    assert main(["run"]) == 2
