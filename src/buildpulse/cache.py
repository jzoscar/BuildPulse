"""Decide which build caches a run uses and where they live.

Two layers are managed:
  conan   prebuilt dependency binaries in a Conan cache (CONAN_HOME)
  ccache  compiler output for the project's own sources (CCACHE_DIR)

Caches are kept per environment (the host, or each Docker image) under the cache root,
default ~/.cache/buildpulse:

    <root>/conan2/<env>/   CONAN_HOME
    <root>/ccache/<env>/   CCACHE_DIR
    <root>/cold/<run>/     throwaway CONAN_HOME for --no-cache / --no-conan-cache runs
"""

from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROOT = Path("~/.cache/buildpulse")


@dataclass
class CacheSettings:
    conan_home: Path
    conan_build: str  # value for `conan install --build=`: "missing" (reuse) or "*" (rebuild all)
    conan_cached: bool
    ccache: bool
    ccache_dir: Path | None
    cold_dir: Path | None = None  # deleted after the run
    env: dict[str, str] = field(default_factory=dict)

    @property
    def mounts(self) -> list[Path]:
        return [p for p in (self.conan_home, self.ccache_dir) if p]

    def describe(self) -> dict:
        return {
            "conan": "warm" if self.conan_cached else "cold",
            "conan_home": str(self.conan_home),
            "conan_build": self.conan_build,
            "ccache": self.ccache,
            "ccache_dir": str(self.ccache_dir) if self.ccache_dir else None,
        }

    def cleanup(self) -> None:
        if self.cold_dir:
            shutil.rmtree(self.cold_dir, ignore_errors=True)


def env_slug(docker_image: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", docker_image).strip("-") if docker_image else "host"


def ccache_available(docker_image: str | None) -> bool:
    if not docker_image:
        return shutil.which("ccache") is not None
    probe = ["docker", "run", "--rm", docker_image, "sh", "-c", "command -v ccache"]
    try:
        return subprocess.run(probe, capture_output=True, check=False).returncode == 0
    except OSError:
        return False


def resolve(
    root: Path,
    docker_image: str | None,
    conan_cache: bool = True,
    ccache: bool = True,
) -> CacheSettings:
    root = root.expanduser().resolve()
    env = env_slug(docker_image)

    cold_dir = None
    if conan_cache:
        conan_home = root / "conan2" / env
    else:
        cold_dir = root / "cold" / uuid.uuid4().hex[:12]
        conan_home = cold_dir / "conan2"
    conan_home.mkdir(parents=True, exist_ok=True)

    use_ccache = ccache and ccache_available(docker_image)
    ccache_dir = root / "ccache" / env if use_ccache else None
    if ccache_dir:
        ccache_dir.mkdir(parents=True, exist_ok=True)

    vars_ = {"CONAN_HOME": str(conan_home)}
    if ccache_dir:
        vars_["CCACHE_DIR"] = str(ccache_dir)
    return CacheSettings(
        conan_home=conan_home,
        conan_build="missing" if conan_cache else "*",
        conan_cached=conan_cache,
        ccache=use_ccache,
        ccache_dir=ccache_dir,
        cold_dir=cold_dir,
        env=vars_,
    )


def parse_ccache_hits(stats_output: str) -> dict | None:
    """Pull hit/miss counts out of `ccache --show-stats` (ccache 4.x)."""
    hits = re.search(r"^\s*Hits:\s+(\d+)\s*/\s*(\d+)", stats_output, re.MULTILINE)
    misses = re.search(r"^\s*Misses:\s+(\d+)\s*/\s*(\d+)", stats_output, re.MULTILINE)
    if not hits:
        return None
    return {
        "hits": int(hits[1]),
        "misses": int(misses[1]) if misses else None,
        "cacheable_calls": int(hits[2]),
    }
