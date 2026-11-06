"""Compare stage timings of two recorded runs, e.g. a cold (--no-cache) and a warm build."""

from __future__ import annotations

import json
from pathlib import Path


def resolve_run(ref: str, log_dir: Path) -> Path:
    """Accept a run directory, a report.json path, a run id, or "latest"."""
    path = Path(ref)
    if path.is_file():
        return path
    for candidate in (path / "report.json", log_dir / ref / "report.json"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"no run '{ref}' (looked in {log_dir})")


def recent_runs(log_dir: Path, count: int) -> list[Path]:
    runs = sorted(p for p in log_dir.iterdir() if p.is_dir() and not p.is_symlink()
                  and (p / "report.json").is_file())
    return [p / "report.json" for p in runs[-count:]]


def _cache_label(report: dict) -> str:
    meta = report.get("meta", {})
    cache = meta.get("cache")
    if not cache:
        return "-"
    label = f"conan={cache['conan']} ccache={'on' if cache['ccache'] else 'off'}"
    stats = meta.get("ccache_stats")
    if stats:
        label += f" ({stats['hits']}/{stats['cacheable_calls']} hits)"
    return label


def render(a: dict, b: dict) -> str:
    times_a = {s["name"]: s["seconds"] for s in a["stages"]}
    times_b = {s["name"]: s["seconds"] for s in b["stages"]}
    names = list(dict.fromkeys([*times_a, *times_b]))

    lines = [
        f"A: {a['run_id']}  {_cache_label(a)}",
        f"B: {b['run_id']}  {_cache_label(b)}",
        "",
        f"  {'stage':<14}{'A':>9}{'B':>9}{'B-A':>9}  speedup",
    ]

    def row(name: str, ta: float | None, tb: float | None) -> str:
        fa = f"{ta:8.2f}s" if ta is not None else f"{'-':>9}"
        fb = f"{tb:8.2f}s" if tb is not None else f"{'-':>9}"
        if ta is None or tb is None:
            return f"  {name:<14}{fa}{fb}"
        speedup = f"{ta / tb:6.1f}x" if tb > 0 else "     -"
        return f"  {name:<14}{fa}{fb}{tb - ta:+8.2f}s  {speedup}"

    for name in names:
        lines.append(row(name, times_a.get(name), times_b.get(name)))
    lines.append(row("total", sum(times_a.values()), sum(times_b.values())))
    if not (a.get("ok") and b.get("ok")):
        lines.append("note: at least one run failed; timings may not be comparable")
    return "\n".join(lines)


def run(refs: list[str], log_dir: Path) -> str:
    paths = [resolve_run(r, log_dir) for r in refs] if refs else recent_runs(log_dir, 2)
    if len(paths) != 2:
        raise FileNotFoundError(f"need two runs to compare (found {len(paths)} in {log_dir})")
    a, b = (json.loads(p.read_text()) for p in paths)
    return render(a, b)
