"""Supply-chain scan of a project: SBOM, SCA and SAST, recorded like any other run.

Stages (all run, even after a failure, so one report shows every finding):
  lock       conan lock create -> <project>/conan.lock, if the project uses Conan and has none
  sbom       Syft -> CycloneDX + SPDX JSON (dependencies from conan.lock and other manifests)
  sca        Trivy on the SBOM: known vulnerabilities; fails at --fail-on severity and above
  sca-sarif  Trivy again, all severities, as SARIF for GitHub code scanning
  sast       Semgrep (C, Python rulesets): fails on ERROR-severity findings

Outputs land in the run directory next to the logs: sbom.cdx.json, sbom.spdx.json,
sca.sarif, sast.sarif, plus report.json with component and finding counts.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from buildpulse.commands.build import CONANFILES
from buildpulse.runner import Recorder, RunReport

SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
SAST_CONFIGS = ["p/c", "p/python"]
SBOM_EXCLUDES = ["./**/build/**", "./**/.buildpulse/**", "./**/.venv/**", "./**/node_modules/**"]


def project_version(project_dir: Path) -> str:
    """`git describe` of the project, so the SBOM says exactly which source it describes."""
    try:
        out = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--tags"],
            cwd=project_dir, capture_output=True, text=True, check=False,
        )
    except OSError:
        return "unknown"
    return out.stdout.strip() or "unknown"


def severities_from(fail_on: str) -> str:
    return ",".join(SEVERITIES[: SEVERITIES.index(fail_on.upper()) + 1])


def plan(project_dir: Path, run_dir: Path, name: str, version: str,
         fail_on: str = "high") -> list[tuple[str, list[str]]]:
    stages: list[tuple[str, list[str]]] = []
    uses_conan = any((project_dir / f).is_file() for f in CONANFILES)
    if uses_conan and not (project_dir / "conan.lock").is_file():
        stages.append(("lock", ["conan", "lock", "create", str(project_dir),
                                "--lockfile-out", str(project_dir / "conan.lock")]))

    cdx, spdx = run_dir / "sbom.cdx.json", run_dir / "sbom.spdx.json"
    sbom = ["syft", "scan", f"dir:{project_dir}", "--source-name", name,
            "--source-version", version, "-o", f"cyclonedx-json={cdx}", "-o", f"spdx-json={spdx}"]
    for pattern in SBOM_EXCLUDES:
        sbom += ["--exclude", pattern]
    stages.append(("sbom", sbom))

    if fail_on != "none":
        stages.append(("sca", ["trivy", "sbom", "--scanners", "vuln", "--format", "table",
                               "--severity", severities_from(fail_on), "--exit-code", "1",
                               str(cdx)]))
    stages.append(("sca-sarif", ["trivy", "sbom", "--scanners", "vuln", "--format", "sarif",
                                 "--output", str(run_dir / "sca.sarif"), str(cdx)]))

    sast = ["semgrep", "scan", "--metrics=off", "--severity", "ERROR", "--error",
            "--sarif-output", str(run_dir / "sast.sarif")]
    for config in SAST_CONFIGS:
        sast += ["--config", config]
    stages.append(("sast", [*sast, str(project_dir)]))
    return stages


def _count_components(path: Path) -> int | None:
    try:
        return len(json.loads(path.read_text()).get("components", []))
    except (OSError, ValueError):
        return None


def _count_sarif(path: Path) -> dict | None:
    try:
        runs = json.loads(path.read_text()).get("runs", [])
    except (OSError, ValueError):
        return None
    counts: dict[str, int] = {}
    for run in runs:
        for result in run.get("results", []):
            level = result.get("level", "warning")
            counts[level] = counts.get(level, 0) + 1
    return counts


def run(project_dir: Path, log_dir: Path, fail_on: str = "high",
        env: dict[str, str] | None = None, echo: bool = True) -> RunReport:
    name = project_dir.name
    version = project_version(project_dir)
    recorder = Recorder(log_dir, kind="scan", label=f"scan-{name}", project_dir=project_dir,
                        echo=echo)
    for stage_name, cmd in plan(project_dir, recorder.run_dir, name, version, fail_on):
        recorder.stage(stage_name, cmd, cwd=project_dir, env=env)  # keep going: report all
    run_dir = recorder.run_dir
    return recorder.finish(
        source={"name": name, "version": version},
        fail_on=fail_on,
        sbom={"cyclonedx": "sbom.cdx.json", "spdx": "sbom.spdx.json",
              "components": _count_components(run_dir / "sbom.cdx.json")},
        sca={"sarif": "sca.sarif", "findings": _count_sarif(run_dir / "sca.sarif")},
        sast={"sarif": "sast.sarif", "findings": _count_sarif(run_dir / "sast.sarif")},
    )
