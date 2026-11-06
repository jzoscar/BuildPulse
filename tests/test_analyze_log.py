from pathlib import Path

from buildpulse.cli import main
from buildpulse.commands import analyze_log

LOGS = Path(__file__).parent / "fixtures" / "logs"


def test_gcc_error_and_warning():
    issues = analyze_log.parse((LOGS / "gcc_undeclared.log").read_text())
    assert [(i.severity, i.line, i.column) for i in issues] == [("error", 14, 12), ("warning", 9, 9)]
    assert issues[0].file == "../../src/checksum.cpp"
    assert "crc_table" in issues[0].message


def test_msvc_error_code():
    issues = analyze_log.parse((LOGS / "msvc_c2065.log").read_text())
    assert issues[0].code == "C2065"
    assert issues[0].file.endswith("checksum.cpp")
    assert issues[1].severity == "warning"


def test_linker_undefined_reference():
    issues = analyze_log.parse((LOGS / "ld_undefined.log").read_text())
    assert len(issues) == 1
    assert issues[0].kind == "linker"
    assert "pulse::crc32" in issues[0].message


def test_clean_log_has_no_issues():
    assert analyze_log.parse("[1/1] Linking CXX executable app\n") == []


def test_cli_accepts_run_reference(tmp_path, capsys):
    run_dir = tmp_path / "20260101-000000-x"
    run_dir.mkdir()
    (run_dir / "full.log").write_text((LOGS / "ld_undefined.log").read_text())
    (tmp_path / "latest.txt").write_text(run_dir.name)
    assert main(["analyze-log", "latest", "--log-dir", str(tmp_path)]) == 1
    assert "undefined reference" in capsys.readouterr().out
    assert main(["analyze-log", "nope", "--log-dir", str(tmp_path)]) == 2


def test_cli_exit_code_reflects_errors(capsys):
    assert main(["analyze-log", str(LOGS / "gcc_undeclared.log")]) == 1
    assert "1 error(s), 1 warning(s)" in capsys.readouterr().out
