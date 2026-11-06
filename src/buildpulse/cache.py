"""Decide which build caches a run uses and where they live.

Two layers are managed:
  conan           prebuilt dependency binaries in a Conan cache (CONAN_HOME)
  compiler cache  compiler output for the project's own sources: ccache (CCACHE_DIR) or
                  sccache (SCCACHE_DIR), set as CMake's compiler launcher

Caches are kept per environment (the host, or each Docker image) under the cache root,
default ~/.cache/buildpulse:

    <root>/conan2/<env>/    CONAN_HOME
    <root>/ccache/<env>/    CCACHE_DIR
    <root>/sccache/<env>/   SCCACHE_DIR
    <root>/cold/<run>/      throwaway CONAN_HOME for --no-cache / --no-conan-cache runs
"""

from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

COMPILER_CACHES = ("ccache", "sccache")  # auto-detection order
_DIR_VARS = {"ccache": "CCACHE_DIR", "sccache": "SCCACHE_DIR"}


@dataclass
class CacheSettings:
    conan_home: Path
    conan_build: str  # value for `conan install --build=`: "missing" (reuse) or "*" (rebuild all)
    conan_cached: bool
    compiler_cache: str | None  # "ccache", "sccache" or None
    compiler_cache_dir: Path | None
    cold_dir: Path | None = None  # deleted after the run
    env: dict[str, str] = field(default_factory=dict)

    @property
    def mounts(self) -> list[Path]:
        return [p for p in (self.conan_home, self.compiler_cache_dir) if p]

    def describe(self) -> dict:
        return {
            "conan": "warm" if self.conan_cached else "cold",
            "conan_home": str(self.conan_home),
            "conan_build": self.conan_build,
            "compiler_cache": self.compiler_cache,
            "compiler_cache_dir": str(self.compiler_cache_dir) if self.compiler_cache_dir else None,
        }

    def cleanup(self) -> None:
        if self.cold_dir:
            shutil.rmtree(self.cold_dir, ignore_errors=True)


def env_slug(docker_image: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", docker_image).strip("-") if docker_image else "host"


def tool_available(tool: str, docker_image: str | None) -> bool:
    if not docker_image:
        return shutil.which(tool) is not None
    probe = ["docker", "run", "--rm", docker_image, "sh", "-c", f"command -v {tool}"]
    try:
        return subprocess.run(probe, capture_output=True, check=False).returncode == 0
    except OSError:
        return False


def pick_compiler_cache(choice: str, docker_image: str | None) -> str | None:
    """Resolve "auto" | "ccache" | "sccache" | "none" to the tool to use, if available."""
    if choice == "none":
        return None
    candidates = COMPILER_CACHES if choice == "auto" else (choice,)
    return next((t for t in candidates if tool_available(t, docker_image)), None)


def resolve(
    root: Path,
    docker_image: str | None,
    conan_cache: bool = True,
    compiler_cache: str = "auto",
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

    tool = pick_compiler_cache(compiler_cache, docker_image)
    tool_dir = root / tool / env if tool else None
    if tool_dir:
        tool_dir.mkdir(parents=True, exist_ok=True)

    vars_ = {"CONAN_HOME": str(conan_home)}
    if tool and tool_dir:
        vars_[_DIR_VARS[tool]] = str(tool_dir)
    return CacheSettings(
        conan_home=conan_home,
        conan_build="missing" if conan_cache else "*",
        conan_cached=conan_cache,
        compiler_cache=tool,
        compiler_cache_dir=tool_dir,
        cold_dir=cold_dir,
        env=vars_,
    )


def parse_stats(tool: str, output: str) -> dict | None:
    """Pull hit/miss counts out of `ccache --show-stats` (4.x) or `sccache --show-stats`."""
    if tool == "sccache":
        hits = re.search(r"^Cache hits\s+(\d+)\s*$", output, re.MULTILINE)
        misses = re.search(r"^Cache misses\s+(\d+)\s*$", output, re.MULTILINE)
        if not hits:
            return None
        n_misses = int(misses[1]) if misses else 0
        return {"hits": int(hits[1]), "misses": n_misses, "cacheable_calls": int(hits[1]) + n_misses}

    hits = re.search(r"^\s*Hits:\s+(\d+)\s*/\s*(\d+)", output, re.MULTILINE)
    misses = re.search(r"^\s*Misses:\s+(\d+)\s*/\s*(\d+)", output, re.MULTILINE)
    if not hits:
        return None
    return {
        "hits": int(hits[1]),
        "misses": int(misses[1]) if misses else None,
        "cacheable_calls": int(hits[2]),
    }


def describe_compiler_cache(cache: dict) -> str:
    """"ccache", "sccache" or "off", also for reports written before sccache support."""
    if "compiler_cache" in cache:
        return cache["compiler_cache"] or "off"
    return "ccache" if cache.get("ccache") else "off"
