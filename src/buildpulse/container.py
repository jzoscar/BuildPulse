"""Wrap a command so it runs inside a Docker image instead of on the host.

Directories are bind-mounted at the same absolute path, so paths in commands, CMake caches
and logs mean the same thing inside and outside the container.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def image_platform(image: str) -> str | None:
    """Return e.g. "linux/amd64" for a local image, or None if it cannot be inspected."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "-f", "{{.Os}}/{{.Architecture}}", image],
            capture_output=True, text=True, check=False,
        )
    except OSError:  # docker not installed; the stage itself will report the failure
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def wrap(
    command: list[str],
    image: str,
    cwd: Path,
    mounts: list[Path],
    platform: str | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    docker = ["docker", "run", "--rm", "-w", str(cwd)]
    if platform:
        # Explicit, so an amd64 image on an arm64 host runs emulated without a warning.
        docker += ["--platform", platform]
    for path in dict.fromkeys(str(p) for p in mounts):  # dedupe, keep order
        docker += ["-v", f"{path}:{path}"]
    if hasattr(os, "getuid"):
        # Files written to the mounts belong to the host user, not root.
        docker += ["--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp"]
    for key, value in (env or {}).items():
        docker += ["-e", f"{key}={value}"]
    return [*docker, image, *command]
