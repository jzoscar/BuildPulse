"""Run an arbitrary build command or script, recording its full output."""

from __future__ import annotations

from pathlib import Path

from buildpulse.runner import Recorder, RunReport


def run(
    command: list[str], cwd: Path, log_dir: Path, name: str | None = None, echo: bool = True
) -> RunReport:
    label = name or Path(command[0]).name
    recorder = Recorder(log_dir, kind="run", label=label, project_dir=cwd, echo=echo)
    recorder.stage(name or "run", command, cwd=cwd)
    return recorder.finish()
