# BuildPulse

A build-tooling CLI. Its first job is to **build any C/C++ project and capture the complete build
log** — every stage, stdout and stderr, exit codes and timings — so the log can be analyzed later.

```
BuildPulse/
├── src/buildpulse/        Python CLI (build, run, analyze-log)
├── tests/                 pytest + real-world build log fixtures
├── native/                internal sample C++ project, used only to test BuildPulse itself
├── buildpulse.toml        defaults for this repo (points at native/)
└── .github/workflows/     CI
```

## Install

Requires Python ≥ 3.11, CMake ≥ 3.24, and a C/C++ compiler (Ninja for the `native/` presets).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## Build your own project

Point `buildpulse build` at any CMake project with `-C` / `--project-dir`:

```bash
# Project without CMakePresets.json: cmake -S <dir> -B <dir>/build/buildpulse
buildpulse build -C ~/code/my-project
buildpulse build -C ~/code/my-project --build-type Release --build-dir /tmp/my-build

# Project with CMakePresets.json: cmake --preset / cmake --build --preset / ctest --preset
buildpulse build -C ~/code/my-project --preset linux-release

# Common flags
buildpulse build -C ~/code/my-project --no-test   # skip ctest
buildpulse build -C ~/code/my-project --clean     # cmake --fresh + --clean-first
```

Stages run in order (configure → build → test) and stop at the first failure. The exit code of
`buildpulse` is the exit code of the failing stage, so it can gate CI.

## Build with your own script

If your project builds through a script, Makefile or anything else, wrap it with `buildpulse run`.
Everything after `--` is run as-is:

```bash
buildpulse run -- ./scripts/build.sh --target arm64
buildpulse run --cwd ~/code/my-project --name nightly -- make -j8
```

## Where the logs go

Every `build` or `run` creates a new run directory:

```
<log dir>/
├── 20261105-180129-host-debug/
│   ├── full.log                 complete output of all stages, in order
│   ├── stages/
│   │   ├── 01-configure.log     one file per stage
│   │   ├── 02-build.log
│   │   └── 03-test.log
│   └── report.json              commands, cwd, exit codes, timings, log paths
└── latest -> 20261105-180129-host-debug
```

- **Default log dir:** `.buildpulse/runs/` under the directory you run `buildpulse` from. Inside
  this repo, that is `<repo>/.buildpulse/runs/` (set by `buildpulse.toml`).
- **Choose a log dir:** `--log-dir <path>` on `build` or `run`.
- Logs are complete: stdout and stderr are merged in order, nothing is truncated, and each stage
  is framed by `==> [stage] <command>` and `<== [stage] exit N in Xs` lines.
- `.buildpulse/` is git-ignored.

## Analyze a log

```bash
buildpulse analyze-log .buildpulse/runs/latest/full.log
buildpulse analyze-log .buildpulse/runs/latest/full.log --json
```

Extracts GCC/Clang, MSVC and linker errors and warnings (file, line, column, code, message).

## Configuration: `buildpulse.toml`

`buildpulse` looks for `buildpulse.toml` in the current directory and its parents. It only sets
defaults; command-line flags always win.

```toml
[project]
dir = "native"          # project used when -C is not given
preset = "host-debug"   # ignored when -C is given
# build_type = "Debug"  # CMAKE_BUILD_TYPE when no preset is used

[logs]
dir = ".buildpulse/runs"
```

The `buildpulse.toml` in this repo points at `native/`, an **internal sample project used only to
test BuildPulse itself**. For real work, always pass `-C <your project>` (or use `run`). Without a
`buildpulse.toml` and without `-C`, the current directory is treated as the project.

## Roadmap

| # | Feature | Status |
|---|---------|--------|
| 1 | Python `buildpulse` CLI + pytest: build any project, capture full logs | ✅ |
| 2 | ARM64 cross-compilation in Docker (GCC + sysroot + CMake toolchain file) | ⬜ |
| 3 | Claude skill: CI log → root cause → fix PR | ⬜ |
| 4 | Conan binary cache | ⬜ |
| 5 | SBOM (Syft) + Trivy / Semgrep in the pipeline | ⬜ |
| 6 | Windows runner with MSVC | ⬜ |
| 7 | Raspberry Pi device test rig running GTest | ⬜ |
| 8 | Bamboo ↔ GitHub Actions concept mapping | ⬜ |
