# BuildPulse

A build-tooling playground: a Python CLI (`buildpulse`) that drives a small C++ project through
configure → build → test, times each stage, and turns raw build logs into structured diagnostics.

```
BuildPulse/
├── src/buildpulse/        Python CLI (build, analyze-log)
├── tests/                 pytest + real-world build log fixtures
├── native/                C++17 project built by the pipeline (CMake presets, GTest)
└── .github/workflows/     CI
```

## Quick start (macOS / Linux)

Requires Python ≥ 3.10, CMake ≥ 3.23, Ninja, and a C++17 compiler.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest -q                                   # Python unit tests
buildpulse build --preset host-debug        # configure + build + ctest
./native/build/host-debug/pulse 123456789   # -> cbf43926
buildpulse analyze-log tests/fixtures/logs/gcc_undeclared.log
```

Each build writes `native/build/<preset>/buildpulse-report.json` with per-stage timings and exit codes.

## Roadmap

| # | Feature | Status |
|---|---------|--------|
| 1 | Python `buildpulse` CLI + pytest | 🟡 skeleton |
| 2 | ARM64 cross-compilation in Docker (GCC + sysroot + CMake toolchain file) | ⬜ |
| 3 | Claude skill: CI log → root cause → fix PR | ⬜ |
| 4 | Conan binary cache | ⬜ |
| 5 | SBOM (Syft) + Trivy / Semgrep in the pipeline | ⬜ |
| 6 | Windows runner with MSVC | ⬜ |
| 7 | Raspberry Pi device test rig running GTest | ⬜ |
| 8 | Bamboo ↔ GitHub Actions concept mapping | ⬜ |
