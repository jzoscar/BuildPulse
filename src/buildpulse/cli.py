"""buildpulse: build C/C++ projects, capture full logs, and analyze them."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from buildpulse import __version__, cache, config
from buildpulse.commands import analyze_log, build, compare, device_test, run, scan, triage
from buildpulse.runner import latest_run


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
    caching = p_build.add_argument_group(
        "dependencies and caching",
        "Caches are on by default. Use --no-cache for a cold, from-scratch build to compare times.")
    caching.add_argument("--deps", choices=["auto", "conan", "none"], default="auto",
                         help="auto: run `conan install` if the project has a conanfile (default)")
    caching.add_argument("--no-cache", action="store_true",
                         help="cold build: empty Conan cache + rebuild all deps from source, "
                              "no compiler cache, clean build tree")
    caching.add_argument("--no-conan-cache", action="store_true",
                         help="use an empty Conan cache and build all deps from source")
    caching.add_argument("--compiler-cache", choices=["auto", "ccache", "sccache", "none"],
                         default="auto",
                         help="compiler launcher cache; auto: ccache, else sccache, if installed")
    caching.add_argument("--no-compiler-cache", "--no-ccache", action="store_true",
                         help="same as --compiler-cache none")
    caching.add_argument("--cache-dir", type=Path,
                         help="cache root (default: [cache] dir in buildpulse.toml, "
                              "else ~/.cache/buildpulse)")
    p_build.set_defaults(func=_run_build)

    p_run = sub.add_parser("run", help="run any build command or script and capture its log",
                           usage="buildpulse run [options] -- COMMAND [ARGS...]")
    p_run.add_argument("--cwd", type=Path, help="directory to run in (default: current directory)")
    p_run.add_argument("--name", help="label for this run (default: the command name)")
    p_run.add_argument("--log-dir", type=Path, help="where run logs go (default: .buildpulse/runs)")
    p_run.add_argument("--docker", metavar="IMAGE", help="run the command inside this Docker image")
    p_run.add_argument("cmd", nargs=argparse.REMAINDER, help="the command to run, after --")
    p_run.set_defaults(func=_run_run)

    p_cmp = sub.add_parser("compare", help="compare stage timings of two runs (default: last two)")
    p_cmp.add_argument("runs", nargs="*", metavar="RUN",
                       help="run id, run directory or report.json; give two, or none for the "
                            "two most recent runs")
    p_cmp.add_argument("--log-dir", type=Path, help="where run logs are (default: .buildpulse/runs)")
    p_cmp.set_defaults(func=_run_compare)

    p_scan = sub.add_parser(
        "scan", help="supply-chain scan: SBOM (Syft), SCA (Trivy), SAST (Semgrep)")
    p_scan.add_argument("-C", "--project-dir", type=Path,
                        help="project to scan (default: [project] dir in buildpulse.toml, "
                             "else the current directory)")
    p_scan.add_argument("--fail-on", choices=["critical", "high", "medium", "low", "none"],
                        default="high",
                        help="fail when SCA finds vulnerabilities at this severity or above "
                             "(default: high)")
    p_scan.add_argument("--log-dir", type=Path, help="where run logs go (default: .buildpulse/runs)")
    p_scan.add_argument("--cache-dir", type=Path, help="cache root (Conan home for the lock stage)")
    p_scan.set_defaults(func=_run_scan)

    p_dev = sub.add_parser(
        "device-test", help="flash a build onto a device borrowed from a LabForge rig pool and test it",
        usage="buildpulse device-test --pool POOL --firmware FILE [options] [-- TEST_COMMAND ...]")
    p_dev.add_argument("--pool", required=True, help="LabForge rig pool to borrow a device from")
    p_dev.add_argument("--firmware", type=Path, required=True, help="build output to install on the device")
    p_dev.add_argument("--version", help="firmware version (default: git describe of the project)")
    p_dev.add_argument("--holder", help="who holds the device (default: the CI run URL, else user@host)")
    p_dev.add_argument("--ttl", type=int, default=1800, help="lease length in seconds (default: 1800)")
    p_dev.add_argument("--labforge", default="labforge", help="labforge CLI to call (default: on PATH)")
    p_dev.add_argument("-C", "--project-dir", type=Path, help="project the build came from")
    p_dev.add_argument("--log-dir", type=Path, help="where run logs go (default: .buildpulse/runs)")
    p_dev.add_argument("test_cmd", nargs=argparse.REMAINDER,
                       help="optional on-device test command after --; gets LABFORGE_DEVICE_HTTP etc.")
    p_dev.set_defaults(func=_run_device_test)

    p_tri = sub.add_parser(
        "triage", help="summarize a failed run for root-cause analysis (human or AI agent)")
    p_tri.add_argument("run", nargs="?", default="latest",
                       help="run id, run directory, report.json, or 'latest' (default)")
    p_tri.add_argument("--log-dir", type=Path, help="where run logs are (default: .buildpulse/runs)")
    p_tri.add_argument("-C", "--project-dir", type=Path,
                       help="local checkout to resolve source files in (default: the run's "
                            "project dir if it exists, else [project] dir in buildpulse.toml)")
    p_tri.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p_tri.add_argument("--context", type=int, default=4, help="source lines around each error")
    p_tri.set_defaults(func=_run_triage)

    p_log = sub.add_parser("analyze-log", help="extract compiler/linker errors from a build log")
    p_log.add_argument("logfile", help="a log file, a run directory, a run id, or 'latest'")
    p_log.add_argument("--log-dir", type=Path, help="where run logs are (default: .buildpulse/runs)")
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

    caches = cache.resolve(
        args.cache_dir or cfg.cache_dir,
        docker_image=args.docker,
        conan_cache=not (args.no_cache or args.no_conan_cache),
        compiler_cache="none" if (args.no_cache or args.no_compiler_cache)
        else args.compiler_cache,
    )
    opts = build.BuildOptions(
        project_dir=project_dir,
        preset=preset,
        build_type=args.build_type or cfg.build_type,
        build_dir=args.build_dir.resolve() if args.build_dir else None,
        run_tests=not args.no_test,
        clean=args.clean or args.no_cache,
        deps=args.deps,
        caches=caches,
    )
    try:
        report = build.run(opts, (args.log_dir or cfg.log_dir).resolve(), docker_image=args.docker)
    finally:
        caches.cleanup()
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


def _run_compare(args: argparse.Namespace) -> int:
    if len(args.runs) not in (0, 2):
        print("buildpulse: compare takes two runs, or none for the last two", file=sys.stderr)
        return 2
    log_dir = (args.log_dir or config.load(Path.cwd()).log_dir).resolve()
    try:
        print(compare.run(args.runs, log_dir))
    except FileNotFoundError as exc:
        print(f"buildpulse: {exc}", file=sys.stderr)
        return 2
    return 0


def _run_scan(args: argparse.Namespace) -> int:
    cfg = config.load(Path.cwd())
    project_dir = (args.project_dir or cfg.project_dir).resolve()
    caches = cache.resolve(args.cache_dir or cfg.cache_dir, None, compiler_cache="none")
    report = scan.run(project_dir, (args.log_dir or cfg.log_dir).resolve(),
                      fail_on=args.fail_on, env={"CONAN_HOME": str(caches.conan_home)})
    print(report.summary())
    meta = report.meta
    print(f"sbom:   {meta['sbom']['components']} components "
          f"({meta['source']['name']} {meta['source']['version']})")
    def findings(counts: dict | None) -> str:
        if counts is None:
            return "no report"
        return ", ".join(f"{n} {level}" for level, n in counts.items()) or "0 findings"

    print(f"sca:    {findings(meta['sca']['findings'])}  (gate: {meta['fail_on']} and above)")
    print(f"sast:   {findings(meta['sast']['findings'])}")
    return report.exit_code


def _default_holder() -> str:
    import getpass
    import os
    import socket

    if os.environ.get("GITHUB_RUN_ID"):
        return (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    return f"{getpass.getuser()}@{socket.gethostname()}"


def _run_device_test(args: argparse.Namespace) -> int:
    if not args.firmware.is_file():
        print(f"buildpulse: firmware {args.firmware} not found", file=sys.stderr)
        return 2
    cfg = config.load(Path.cwd())
    project_dir = (args.project_dir or cfg.project_dir).resolve()
    test_cmd = args.test_cmd[1:] if args.test_cmd[:1] == ["--"] else args.test_cmd
    report = device_test.run(
        args.pool, args.firmware.resolve(), args.version or scan.project_version(project_dir),
        (args.log_dir or cfg.log_dir).resolve(), holder=args.holder or _default_holder(),
        test_cmd=test_cmd or None, project_dir=project_dir, labforge=args.labforge, ttl=args.ttl,
    )
    print(report.summary())
    meta = report.meta
    device = (meta.get("device") or {}).get("device") or "-"
    print(f"device: {device}  firmware {meta['firmware']['version']} (sha256 {meta['firmware']['sha256'][:12]})"
          f"  result: {meta['result']}")
    return report.exit_code


def _run_triage(args: argparse.Namespace) -> int:
    cfg = config.load(Path.cwd())
    log_dir = (args.log_dir or cfg.log_dir).resolve()
    try:
        report = compare.resolve_run(args.run, log_dir)
    except FileNotFoundError as exc:
        print(f"buildpulse: {exc}", file=sys.stderr)
        return 2
    project_dir = (args.project_dir or cfg.project_dir).resolve()
    result = triage.build(report, project_dir, context=args.context)
    print(result.to_json() if args.json else result.to_markdown())
    return 0


def _resolve_log(ref: str, log_dir: Path) -> Path | None:
    path = Path(ref)
    if path.is_file():
        return path
    run_dir = latest_run(log_dir) if ref == "latest" else (
        path if path.is_dir() else log_dir / ref)
    full_log = run_dir / "full.log" if run_dir else None
    return full_log if full_log and full_log.is_file() else None


def _run_analyze_log(args: argparse.Namespace) -> int:
    log_dir = (args.log_dir or config.load(Path.cwd()).log_dir).resolve()
    logfile = _resolve_log(args.logfile, log_dir)
    if logfile is None:
        print(f"buildpulse: no log '{args.logfile}' (looked in {log_dir})", file=sys.stderr)
        return 2
    issues = analyze_log.parse(logfile.read_text(errors="replace"))
    print(analyze_log.render(issues, as_json=args.json))
    return 1 if any(i.severity == "error" for i in issues) else 0


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
