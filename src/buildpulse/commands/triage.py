"""Turn a failed run into a compact triage bundle for a human or an AI agent.

Instead of handing someone (or an LLM) a 10,000-line log, the bundle holds what a root-cause
analysis starts from: which stage failed and with what command, the build environment, the
extracted compiler/linker/test diagnostics with the source lines they point at, and the tail of
the failing stage's log.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from buildpulse.commands import analyze_log

_CTEST_FAILED = re.compile(r"^\s*\d+\s+-\s+(?P<name>\S+)\s+\((?P<why>[^)]+)\)\s*$")
_GTEST_FAILED = re.compile(r"^\[\s+FAILED\s+\]\s+(?P<name>\S+\.\S+)")


@dataclass
class SourceContext:
    file: str  # path relative to the project (or absolute), always with forward slashes
    line: int
    snippet: str  # numbered lines around `line`, the offending one marked with ">"


@dataclass
class Triage:
    run_id: str
    ok: bool
    category: str  # success | dependencies | configure | compile | link | test | command
    failed_stage: str | None = None
    command: list[str] = field(default_factory=list)
    exit_code: int = 0
    environment: dict = field(default_factory=dict)
    diagnostics: list[dict] = field(default_factory=list)
    failed_tests: list[str] = field(default_factory=list)
    sources: list[SourceContext] = field(default_factory=list)
    log_tail: str = ""
    stage_log: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def to_markdown(self) -> str:
        if self.ok:
            return f"### buildpulse triage: `{self.run_id}`\n\nAll stages passed.\n"
        env = ", ".join(f"{k}={v}" for k, v in self.environment.items() if v) or "-"
        out = [
            f"### buildpulse triage: `{self.run_id}`",
            "",
            f"- **Category:** {self.category}",
            f"- **Failed stage:** `{self.failed_stage}` (exit {self.exit_code})",
            f"- **Command:** `{' '.join(self.command)}`",
            f"- **Environment:** {env}",
            f"- **Stage log:** `{self.stage_log}`",
        ]
        if self.diagnostics:
            out += ["", "#### Diagnostics", ""]
            for d in self.diagnostics:
                loc = f"{d['file']}:{d['line']}" if d.get("file") else "<link>"
                code = f" [{d['code']}]" if d.get("code") else ""
                out.append(f"- {d['severity']} ({d['kind']}) `{loc}`{code}: {d['message']}")
        if self.failed_tests:
            out += ["", "#### Failed tests", ""] + [f"- `{t}`" for t in self.failed_tests]
        for src in self.sources:
            out += ["", f"#### `{src.file}:{src.line}`", "", "```cpp", src.snippet, "```"]
        out += ["", "#### Log tail", "", "```", self.log_tail, "```", ""]
        return "\n".join(out)


def _category(stage: str, issues: list[analyze_log.Issue], failed_tests: list[str]) -> str:
    errors = [i for i in issues if i.severity == "error"]
    if stage in ("deps", "conan-profile"):
        return "dependencies"
    if stage == "configure":
        return "configure"
    if stage == "test" or failed_tests:
        return "test"
    if any(i.kind == "linker" for i in errors):
        return "link"
    if errors:
        return "compile"
    return "command"


def _failed_tests(log: str) -> list[str]:
    names = [m["name"] for line in log.splitlines()
             if (m := _CTEST_FAILED.match(line) or _GTEST_FAILED.match(line))]
    return list(dict.fromkeys(names))


def locate_source(file: str, project_dir: Path, build_dir: Path | None = None) -> Path | None:
    """Find a diagnostic's file locally, even when the log came from another machine/container."""
    raw = Path(file.replace("\\", "/"))
    candidates = [raw] if raw.is_absolute() else [(build_dir or project_dir) / raw, project_dir / raw]
    for c in candidates:
        if c.is_file():
            return c.resolve()
    # Paths from CI or a container: match the longest tail that exists under the project.
    parts = [p for p in raw.parts if p not in ("/", "..", ".") and not p.endswith(":")]
    for start in range(len(parts)):
        candidate = project_dir.joinpath(*parts[start:])
        if candidate.is_file():
            return candidate.resolve()
    return None


def _snippet(path: Path, line: int, context: int) -> str:
    lines = path.read_text(errors="replace").splitlines()
    lo, hi = max(1, line - context), min(len(lines), line + context)
    return "\n".join(
        f"{'>' if n == line else ' '}{n:5d} | {lines[n - 1]}" for n in range(lo, hi + 1)
    )


def unwrap_docker(command: list[str], image: str | None) -> list[str]:
    """The command as run inside the container, without the `docker run ...` wrapper."""
    if image and command[:2] == ["docker", "run"] and image in command:
        return command[command.index(image) + 1:]
    return command


def build(report_path: Path, project_dir: Path, context: int = 4, tail: int = 60) -> Triage:
    report = json.loads(report_path.read_text())
    run_dir = report_path.parent
    meta = report.get("meta", {})
    environment = {
        "kind": report.get("kind"),
        "preset": meta.get("preset"),
        "build_type": meta.get("build_type"),
        "docker_image": meta.get("docker_image"),
        "deps": meta.get("deps"),
    }
    failed = next((s for s in report["stages"] if s["returncode"] != 0), None)
    if failed is None:
        return Triage(run_id=report["run_id"], ok=True, category="success", environment=environment)

    log = (run_dir / failed["log"]).read_text(errors="replace")
    issues = analyze_log.parse(log)
    failed_tests = _failed_tests(log)

    reported_project = Path(report.get("project_dir", ""))
    if reported_project.is_dir():
        project_dir = reported_project
    build_dir = Path(meta["build_dir"]) if meta.get("build_dir") else None
    if meta.get("preset") and build_dir is None:
        build_dir = project_dir / "build" / meta["preset"]

    sources: list[SourceContext] = []
    for issue in issues:
        if issue.severity != "error" or not issue.file or not issue.line or len(sources) >= 5:
            continue
        found = locate_source(issue.file, project_dir, build_dir)
        if found:
            try:
                shown = found.relative_to(project_dir.resolve()).as_posix()
            except ValueError:
                shown = found.as_posix()
            sources.append(SourceContext(shown, issue.line, _snippet(found, issue.line, context)))

    return Triage(
        run_id=report["run_id"],
        ok=False,
        category=_category(failed["name"], issues, failed_tests),
        failed_stage=failed["name"],
        command=unwrap_docker(failed["command"], meta.get("docker_image")),
        exit_code=failed["returncode"],
        environment=environment,
        diagnostics=[asdict(i) for i in issues],
        failed_tests=failed_tests,
        sources=sources,
        log_tail="\n".join(log.splitlines()[-tail:]),
        stage_log=str(run_dir / failed["log"]),
    )
