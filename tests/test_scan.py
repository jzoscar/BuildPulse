import json
from pathlib import Path

from buildpulse.commands import build, scan


def names(stages):
    return [n for n, _ in stages]


def test_plan_creates_lock_only_when_missing(tmp_path):
    (tmp_path / "conanfile.py").write_text("")
    run_dir = tmp_path / "run"
    assert names(scan.plan(tmp_path, run_dir, "p", "v1"))[0] == "lock"
    (tmp_path / "conan.lock").write_text("{}")
    assert names(scan.plan(tmp_path, run_dir, "p", "v1")) == ["sbom", "sca", "sca-sarif", "sast"]


def test_plan_without_conan_and_without_gate(tmp_path):
    stages = dict(scan.plan(tmp_path, tmp_path / "run", "p", "v1", fail_on="none"))
    assert list(stages) == ["sbom", "sca-sarif", "sast"]
    sbom = stages["sbom"]
    assert f"cyclonedx-json={tmp_path / 'run' / 'sbom.cdx.json'}" in sbom
    assert sbom[sbom.index("--source-version") + 1] == "v1"
    assert "./**/build/**" in sbom


def test_severity_gate():
    assert scan.severities_from("critical") == "CRITICAL"
    assert scan.severities_from("high") == "CRITICAL,HIGH"
    stages = dict(scan.plan(Path("/p"), Path("/r"), "p", "v", fail_on="medium"))
    assert "CRITICAL,HIGH,MEDIUM" in stages["sca"]


def test_counts(tmp_path):
    (tmp_path / "s.cdx.json").write_text(json.dumps({"components": [{}, {}]}))
    (tmp_path / "r.sarif").write_text(json.dumps({"runs": [{"results": [
        {"level": "error"}, {"level": "error"}, {"level": "warning"}]}]}))
    assert scan._count_components(tmp_path / "s.cdx.json") == 2
    assert scan._count_sarif(tmp_path / "r.sarif") == {"error": 2, "warning": 1}
    assert scan._count_sarif(tmp_path / "missing.sarif") is None


def test_build_uses_committed_lockfile(tmp_path):
    (tmp_path / "conanfile.py").write_text("")
    (tmp_path / "conan.lock").write_text("{}")
    deps = dict(build.plan(build.BuildOptions(tmp_path)))["deps"]
    assert deps[deps.index("--lockfile") + 1] == str(tmp_path / "conan.lock")
