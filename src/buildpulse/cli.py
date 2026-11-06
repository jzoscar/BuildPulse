"""buildpulse command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from buildpulse import __version__
from buildpulse.commands import analyze_log, build


def _find_project_root(start: Path) -> Path:
    """Walk up from `start` until a directory containing native/CMakePresets.json is found."""
    for path in [start, *start.parents]:
        if (path / "native" / "CMakePresets.json").is_file():
            return path
    raise SystemExit("buildpulse: could not find native/CMakePresets.json above the current directory")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buildpulse", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="configure, build and test a CMake preset")
    p_build.add_argument("--preset", default="host-debug", help="CMake preset name")
    p_build.add_argument("--no-test", action="store_true", help="skip the ctest stage")
    p_build.add_argument("--clean", action="store_true", help="remove the build dir first")
    p_build.set_defaults(func=_run_build)

    p_log = sub.add_parser("analyze-log", help="extract compiler/linker errors from a build log")
    p_log.add_argument("logfile", type=Path)
    p_log.add_argument("--json", action="store_true", help="print machine-readable JSON")
    p_log.set_defaults(func=_run_analyze_log)

    return parser


def _run_build(args: argparse.Namespace) -> int:
    root = _find_project_root(Path.cwd())
    report = build.run(
        native_dir=root / "native",
        preset=args.preset,
        run_tests=not args.no_test,
        clean=args.clean,
    )
    print(report.summary())
    return 0 if report.ok else 1


def _run_analyze_log(args: argparse.Namespace) -> int:
    issues = analyze_log.parse(args.logfile.read_text(errors="replace"))
    print(analyze_log.render(issues, as_json=args.json))
    return 1 if any(i.severity == "error" for i in issues) else 0


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
