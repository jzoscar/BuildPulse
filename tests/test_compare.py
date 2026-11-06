import json

from buildpulse.cli import main
from buildpulse.commands import compare


def write_run(log_dir, run_id, stages, cache=None, ok=True):
    d = log_dir / run_id
    d.mkdir(parents=True)
    report = {"run_id": run_id, "ok": ok, "meta": {"cache": cache} if cache else {},
              "stages": [{"name": n, "seconds": s} for n, s in stages]}
    (d / "report.json").write_text(json.dumps(report))


def test_render_shows_per_stage_delta_and_speedup():
    a = {"run_id": "cold", "ok": True, "meta": {}, "stages": [
        {"name": "deps", "seconds": 20.0}, {"name": "build", "seconds": 4.0}]}
    b = {"run_id": "warm", "ok": True, "meta": {}, "stages": [
        {"name": "deps", "seconds": 2.0}, {"name": "ccache-zero", "seconds": 0.5},
        {"name": "build", "seconds": 2.0}]}
    out = compare.render(a, b)
    assert "deps" in out and "10.0x" in out
    assert "ccache-zero" in out
    total = next(line for line in out.splitlines() if line.strip().startswith("total"))
    assert "24.00s" in total and "4.50s" in total


def test_cli_defaults_to_last_two_runs(tmp_path, capsys):
    cache = {"conan": "cold", "ccache": False}
    write_run(tmp_path, "20260101-000000-a", [("build", 9.0)], cache)
    write_run(tmp_path, "20260101-000001-b", [("build", 3.0)])
    write_run(tmp_path, "20260101-000002-c", [("build", 1.0)])
    assert main(["compare", "--log-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "A: 20260101-000001-b" in out and "B: 20260101-000002-c" in out


def test_cli_explicit_runs_and_errors(tmp_path, capsys):
    write_run(tmp_path, "x", [("build", 2.0)])
    write_run(tmp_path, "y", [("build", 1.0)], ok=False)
    assert main(["compare", "--log-dir", str(tmp_path), "x", "y"]) == 0
    assert "at least one run failed" in capsys.readouterr().out
    assert main(["compare", "--log-dir", str(tmp_path), "x", "nope"]) == 2
    assert main(["compare", "--log-dir", str(tmp_path), "x"]) == 2
