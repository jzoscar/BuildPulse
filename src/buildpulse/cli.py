"""buildpulse: build C/C++ projects, capture full logs, and analyze them."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from buildpulse import __version__, config
from buildpulse.commands import analyze_log, build, run


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buildpulse", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="configure, build and test a CMake project")
    p_build.add_argument("-C", "--project-dir", type=Path,
                         help="CMake project to build (default: [project] dir in buildpulse.toml, "
                              "else the current directory)")
    p_build.add_argument("--preset", help="CMake preset; omit to build without presets")
    p_build.add_argument("--build-type", help="CMAKE_BUILD_TYPE when not using a preset")
    p_build.add_argument("--build-dir", type=Path,
                         help=f"build tree when not using a preset (default: <project>/"
                              f"{build.DEFAULT_BUILD_DIR})")
    p_build.add_argument("--log-dir", type=Path, help="where run logs go (default: .buildpulse/runs)")
    p_build.add_argument("--no-test", action="store_true", help="skip the ctest stage")
    p_build.add_argument("--clean", action="store_true", help="reconfigure fresh and rebuild all")
    p_build.add_argument("--docker", metavar="IMAGE",
                         help="run every stage inside this Docker image (e.g. buildpulse/cross-arm64)")
    p_build.set_defaults(func=_run_build)

    p_run = sub.add_parser("run", help="run any build command or script and capture its log",
                           usage="buildpulse run [options] -- COMMAND [ARGS...]")
    p_run.add_argument("--cwd", type=Path, help="directory to run in (default: current directory)")
    p_run.add_argument("--name", help="label for this run (default: the command name)")
    p_run.add_argument("--log-dir", type=Path, help="where run logs go (default: .buildpulse/runs)")
    p_run.add_argument("--docker", metavar="IMAGE", help="run the command inside this Docker image")
    p_run.add_argument("cmd", nargs=argparse.REMAINDER, help="the command to run, after --")
    p_run.set_defaults(func=_run_run)

    p_log = sub.add_parser("analyze-log", help="extract compiler/linker errors from a build log")
    p_log.add_argument("logfile", type=Path)
    p_log.add_argument("--json", action="store_true", help="print machine-readable JSON")
    p_log.set_defaults(func=_run_analyze_log)

    return parser


def _run_build(args: argparse.Namespace) -> int:
    cfg = config.load(Path.cwd())
    if args.project_dir:
        project_dir = args.project_dir.resolve()
        preset = args.preset  # a different project: don't inherit the configured preset
    else:
        project_dir = cfg.project_dir
        preset = args.preset or cfg.preset

    error = build.validate(project_dir, preset)
    if error:
        print(f"buildpulse: {error}", file=sys.stderr)
        return 2

    report = build.run(
        project_dir=project_dir,
        log_dir=(args.log_dir or cfg.log_dir).resolve(),
        preset=preset,
        build_type=args.build_type or cfg.build_type,
        build_dir=args.build_dir.resolve() if args.build_dir else None,
        run_tests=not args.no_test,
        clean=args.clean,
        docker_image=args.docker,
    )
    print(report.summary())
    return report.exit_code


def _run_run(args: argparse.Namespace) -> int:
    command = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not command:
        print("buildpulse: run needs a command, e.g. buildpulse run -- ./build.sh", file=sys.stderr)
        return 2
    cfg = config.load(Path.cwd())
    report = run.run(
        command,
        cwd=(args.cwd or Path.cwd()).resolve(),
        log_dir=(args.log_dir or cfg.log_dir).resolve(),
        name=args.name,
        docker_image=args.docker,
    )
    print(report.summary())
    return report.exit_code


def _run_analyze_log(args: argparse.Namespace) -> int:
    issues = analyze_log.parse(args.logfile.read_text(errors="replace"))
    print(analyze_log.render(issues, as_json=args.json))
    return 1 if any(i.severity == "error" for i in issues) else 0


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
