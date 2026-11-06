"""Drive a CMake preset through configure -> build -> test, timing each stage."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Stage:
    name: str
    command: list[str]
    returncode: int
    seconds: float


@dataclass
class BuildReport:
    preset: str
    build_dir: str
    stages: list[Stage] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.returncode == 0 for s in self.stages)

    def summary(self) -> str:
        lines = [f"preset: {self.preset}"]
        for s in self.stages:
            status = "ok" if s.returncode == 0 else f"FAILED ({s.returncode})"
            lines.append(f"  {s.name:<10} {s.seconds:7.2f}s  {status}")
        total = sum(s.seconds for s in self.stages)
        lines.append(f"  {'total':<10} {total:7.2f}s  {'ok' if self.ok else 'FAILED'}")
        lines.append(f"report: {self.build_dir}/buildpulse-report.json")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps({**asdict(self), "ok": self.ok}, indent=2)


def plan(preset: str, run_tests: bool) -> list[tuple[str, list[str]]]:
    """Return the (stage name, command) pairs for a preset, in order."""
    stages = [
        ("configure", ["cmake", "--preset", preset]),
        ("build", ["cmake", "--build", "--preset", preset]),
    ]
    if run_tests:
        stages.append(("test", ["ctest", "--preset", preset]))
    return stages


def run(native_dir: Path, preset: str, run_tests: bool = True, clean: bool = False) -> BuildReport:
    build_dir = native_dir / "build" / preset
    if clean and build_dir.exists():
        shutil.rmtree(build_dir)

    report = BuildReport(preset=preset, build_dir=str(build_dir))
    for name, cmd in plan(preset, run_tests):
        print(f"==> {name}: {' '.join(cmd)}", flush=True)
        start = time.monotonic()
        rc = subprocess.run(cmd, check=False, cwd=native_dir).returncode
        report.stages.append(Stage(name, cmd, rc, round(time.monotonic() - start, 3)))
        if rc != 0:
            break

    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "buildpulse-report.json").write_text(report.to_json())
    return report
