"""Run commands while capturing their full output to log files.

Every invocation gets its own run directory:

    <log_dir>/<run_id>/
        full.log              all stages, in order, with stage headers
        stages/01-<name>.log  one file per stage
        report.json           what ran, where, how long, exit codes, log paths

and <log_dir>/latest points at the newest run.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class Stage:
    name: str
    command: list[str]
    cwd: str
    returncode: int
    seconds: float
    log: str  # relative to the run directory
    env: dict[str, str] = field(default_factory=dict)  # variables set on top of os.environ


@dataclass
class RunReport:
    run_id: str
    kind: str
    project_dir: str
    started_at: str
    run_dir: str
    full_log: str = "full.log"
    finished_at: str | None = None
    stages: list[Stage] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.stages) and all(s.returncode == 0 for s in self.stages)

    @property
    def exit_code(self) -> int:
        failed = [s.returncode for s in self.stages if s.returncode != 0]
        return failed[0] if failed else 0

    def summary(self) -> str:
        lines = [f"run: {self.run_id}  ({self.kind}, {self.project_dir})"]
        for s in self.stages:
            status = "ok" if s.returncode == 0 else f"FAILED ({s.returncode})"
            lines.append(f"  {s.name:<13} {s.seconds:7.2f}s  {status}")
        total = sum(s.seconds for s in self.stages)
        lines.append(f"  {'total':<13} {total:7.2f}s  {'ok' if self.ok else 'FAILED'}")
        if self.meta.get("cache"):
            c, stats = self.meta["cache"], self.meta.get("ccache_stats")
            hits = f" (hits {stats['hits']}/{stats['cacheable_calls']})" if stats else ""
            ccache = "on" if c["ccache"] else "off"
            lines.append(f"cache:  conan={c['conan']}  ccache={ccache}{hits}")
        lines.append(f"log:    {Path(self.run_dir) / self.full_log}")
        lines.append(f"report: {Path(self.run_dir) / 'report.json'}")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {**asdict(self), "ok": self.ok, "exit_code": self.exit_code}, indent=2
        )


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "run"


class Recorder:
    """Runs stages one after another, teeing output to the terminal and to log files."""

    def __init__(self, log_dir: Path, kind: str, label: str, project_dir: Path, echo: bool = True):
        now = datetime.now(UTC).astimezone()
        run_id = f"{now:%Y%m%d-%H%M%S}-{_slug(label)}"
        self.run_dir = log_dir / run_id
        suffix = 1
        while self.run_dir.exists():
            suffix += 1
            self.run_dir = log_dir / f"{run_id}-{suffix}"
        (self.run_dir / "stages").mkdir(parents=True)
        self.log_dir = log_dir
        self.echo = echo
        self.report = RunReport(
            run_id=self.run_dir.name,
            kind=kind,
            project_dir=str(project_dir),
            started_at=now.isoformat(timespec="seconds"),
            run_dir=str(self.run_dir),
        )

    def stage(
        self, name: str, command: list[str], cwd: Path, env: dict[str, str] | None = None
    ) -> Stage:
        index = len(self.report.stages) + 1
        rel_log = f"stages/{index:02d}-{_slug(name)}.log"
        env = env or {}
        header = f"==> [{name}] {shlex.join(command)}  (cwd: {cwd})\n"
        if env:
            header += "    env: " + " ".join(f"{k}={v}" for k, v in env.items()) + "\n"

        start = time.monotonic()
        with open(self.run_dir / "full.log", "ab") as full, open(self.run_dir / rel_log, "wb") as part:
            self._emit(header.encode(), full, part)
            try:
                proc = subprocess.Popen(
                    command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    env={**os.environ, **env},
                )
            except OSError as exc:
                self._emit(f"buildpulse: cannot start command: {exc}\n".encode(), full, part)
                returncode = 127
            else:
                for chunk in iter(lambda: proc.stdout.readline(), b""):
                    self._emit(chunk, full, part)
                returncode = proc.wait()
            elapsed = time.monotonic() - start
            self._emit(f"<== [{name}] exit {returncode} in {elapsed:.2f}s\n\n".encode(), full, part)

        stage = Stage(name, command, str(cwd), returncode, round(elapsed, 3), rel_log, env)
        self.report.stages.append(stage)
        self._write_report()
        return stage

    def finish(self, **meta) -> RunReport:
        self.report.meta.update(meta)
        self.report.finished_at = datetime.now(UTC).astimezone().isoformat(
            timespec="seconds"
        )
        self._write_report()
        self._point_latest()
        return self.report

    def _emit(self, data: bytes, *files) -> None:
        for f in files:
            f.write(data)
        if self.echo:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

    def _write_report(self) -> None:
        (self.run_dir / "report.json").write_text(self.report.to_json())

    def _point_latest(self) -> None:
        latest = self.log_dir / "latest"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            os.symlink(self.run_dir.name, latest, target_is_directory=True)
        except OSError:
            pass  # e.g. Windows without symlink rights; report.json still has run_dir
