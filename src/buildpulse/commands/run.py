"""Run an arbitrary build command or script, recording its full output."""

from __future__ import annotations

from pathlib import Path

from buildpulse import container
from buildpulse.runner import Recorder, RunReport


def run(
    command: list[str],
    cwd: Path,
    log_dir: Path,
    name: str | None = None,
    docker_image: str | None = None,
    echo: bool = True,
) -> RunReport:
    label = name or Path(command[0]).name
    recorder = Recorder(log_dir, kind="run", label=label, project_dir=cwd, echo=echo)
    if docker_image:
        command = container.wrap(
            command, docker_image, cwd, [cwd], container.image_platform(docker_image)
        )
    recorder.stage(name or "run", command, cwd=cwd)
    return recorder.finish(docker_image=docker_image)
