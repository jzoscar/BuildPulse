"""Load defaults from buildpulse.toml; command-line flags override them."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "buildpulse.toml"
DEFAULT_LOG_DIR = ".buildpulse/runs"
DEFAULT_CACHE_DIR = "~/.cache/buildpulse"


@dataclass
class Config:
    root: Path  # directory relative paths are resolved against
    project_dir: Path
    preset: str | None
    build_type: str
    log_dir: Path
    cache_dir: Path
    source: Path | None  # the buildpulse.toml that was loaded, if any


def find_config(start: Path) -> Path | None:
    for path in [start, *start.parents]:
        candidate = path / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load(start: Path) -> Config:
    """Read the nearest buildpulse.toml at or above `start`, or fall back to `start` itself."""
    source = find_config(start)
    root = source.parent if source else start
    data = tomllib.loads(source.read_text()) if source else {}
    project = data.get("project", {})
    logs = data.get("logs", {})
    caches = data.get("cache", {})
    return Config(
        root=root,
        project_dir=(root / project.get("dir", ".")).resolve(),
        preset=project.get("preset"),
        build_type=project.get("build_type", "Debug"),
        log_dir=(root / logs.get("dir", DEFAULT_LOG_DIR)).resolve(),
        cache_dir=(root / Path(caches.get("dir", DEFAULT_CACHE_DIR)).expanduser()).resolve(),
        source=source,
    )
