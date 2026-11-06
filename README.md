# BuildPulse

A build-tooling CLI. Its first job is to **build any C/C++ project and capture the complete build
log** — every stage, stdout and stderr, exit codes and timings — so the log can be analyzed later.

```
BuildPulse/
├── src/buildpulse/        Python CLI (build, run, compare, triage, scan, analyze-log)
├── .claude/skills/        ci-triage agent skill for Claude Code
├── tests/                 pytest + real-world build log fixtures
├── native/                internal sample C++ project, used only to test BuildPulse itself
├── docker/                cross-compilation images
├── toolchains/            CMake toolchain files, Conan profiles
├── buildpulse.toml        defaults for this repo (points at native/)
└── .github/workflows/     CI
```

## Install

Requires Python ≥ 3.11, CMake ≥ 3.24, a C/C++ compiler (Ninja for the `native/` presets).
Optional: Conan 2 (`pip install -e ".[conan]"`, included in `.[dev]`) and ccache or sccache for caching,
Docker for cross-compilation, Syft + Trivy + Semgrep for `buildpulse scan`.

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

Stages run in order (deps → configure → build → test) and stop at the first failure. The `deps`
stage (`conan install`) only runs when the project has a `conanfile.py` / `conanfile.txt`; see
[Build caching](#build-caching). The exit code of
`buildpulse` is the exit code of the failing stage, so it can gate CI.

## Build with your own script

If your project builds through a script, Makefile or anything else, wrap it with `buildpulse run`.
Everything after `--` is run as-is:

```bash
buildpulse run -- ./scripts/build.sh --target arm64
buildpulse run --cwd ~/code/my-project --name nightly -- make -j8
```

## Cross-compile for ARM64 (aarch64 Linux)

Any stage can run inside a Docker image with `--docker IMAGE`. The project (and `--build-dir`, if
given) is mounted at the same absolute path, so logs and CMake caches stay valid on the host.

The `buildpulse/cross-arm64` image (`docker/cross-arm64.Dockerfile`) cross-compiles from an
x86_64 Linux host to aarch64 Linux:

| Piece | What it is |
|-------|------------|
| Compiler | Debian GCC 12 cross toolchain, `aarch64-linux-gnu-gcc/g++` |
| Sysroot | `/opt/sysroot/aarch64-linux-gnu`, unpacked from Debian **bookworm arm64** packages — the same glibc 2.36 / libstdc++ as Raspberry Pi OS bookworm |
| Toolchain file | `toolchains/aarch64-linux-gnu.cmake`, copied to `/opt/buildpulse/toolchains/` and set as `CMAKE_TOOLCHAIN_FILE`, so any CMake project cross-compiles without changes |
| Emulator | `qemu-aarch64`, set as `CMAKE_CROSSCOMPILING_EMULATOR`, so `ctest` runs the aarch64 tests |

```bash
docker build -t buildpulse/cross-arm64 -f docker/cross-arm64.Dockerfile .

# Your project (no preset needed: the image's CMAKE_TOOLCHAIN_FILE does the cross setup)
buildpulse build -C ~/code/my-project --docker buildpulse/cross-arm64 --build-type Release

# Your own build script, run inside the image
buildpulse run --cwd ~/code/my-project --docker buildpulse/cross-arm64 -- ./build.sh

# Internal sample project, via its linux-arm64 preset
buildpulse build --preset linux-arm64 --docker buildpulse/cross-arm64
```

Libraries your project links against must exist in the sysroot. Add their arm64 `-dev` packages:

```bash
docker build -t buildpulse/cross-arm64 -f docker/cross-arm64.Dockerfile \
  --build-arg SYSROOT_EXTRA_PACKAGES="zlib1g-dev:arm64 libssl-dev:arm64" .
```

On an Apple Silicon Mac, Docker can come from [Colima](https://github.com/abiosoft/colima):
`brew install colima docker && colima start --vm-type vz --vz-rosetta`. The image is linux/amd64
and runs under Rosetta. Colima only shares your home directory, so projects must live under `~`.

## Build with MSVC on Windows

The same project, the same tool, a different compiler: `windows-msvc` builds with MSVC (`cl.exe`)
and Ninja from a Visual Studio developer environment.

```powershell
# In an "x64 Native Tools Command Prompt for VS" (or after ilammy/msvc-dev-cmd in CI)
pip install -e ".[conan]"
buildpulse build --preset windows-msvc --compiler-cache sccache
```

| Piece | What it is |
|-------|------------|
| Compiler | MSVC 19.5x (`cl.exe`), x64, `/W4 /permissive-`, set by the `windows-msvc` preset |
| Generator | Ninja (compiler launchers such as sccache only work with Ninja/Makefiles, not the VS generator) |
| Dependencies | Conan with the detected `msvc` profile (`compiler.version=195`, dynamic runtime); `buildpulse` pins Conan's CMake toolchain to the preset's generator so it does not emit Visual Studio platform/toolset settings |
| Compiler cache | **sccache** (first-class MSVC support). `CMAKE_MSVC_DEBUG_INFORMATION_FORMAT=Embedded` (`/Z7`, policy CMP0141) keeps debug info in the objects so they are cacheable |
| CI | `.github/workflows/windows-msvc.yml` on `windows-latest`: runs the pytest suite on Windows first (buildpulse itself must be portable), then builds, runs the GTest suite and the binary |

No local Windows machine is needed: GitHub-hosted Windows runners are free for public repositories.
Portability fixes this surfaced in buildpulse: `latest` is a symlink plus a `latest.txt` marker
(symlinks need a privilege on Windows), toolchain paths are passed with forward slashes, and the
test suite no longer assumes POSIX commands.

## Build caching

Caches are **on by default**. Turn them off to get a cold, from-scratch baseline, then compare:

| Flag | Effect |
|------|--------|
| *(none)* | Warm: reuse Conan packages (`--build=missing`) and the compiler cache |
| `--no-cache` | Cold: empty throwaway Conan cache, all deps rebuilt from source (`--build=*`), no compiler cache, clean build tree (`--clean`) |
| `--no-conan-cache` | Only the Conan layer cold |
| `--no-compiler-cache` | Only the compiler cache off (alias `--no-ccache`) |
| `--compiler-cache auto\|ccache\|sccache\|none` | Pick the compiler cache (default `auto`: ccache, else sccache, if installed) |
| `--deps conan\|none\|auto` | Force or skip the Conan `deps` stage (default `auto`: if a conanfile exists) |
| `--cache-dir DIR` | Cache root (default `~/.cache/buildpulse`, or `[cache] dir` in `buildpulse.toml`) |

```bash
buildpulse build -C ~/code/my-project --no-cache   # cold baseline
buildpulse build -C ~/code/my-project --clean      # warm-up: fills the caches
buildpulse build -C ~/code/my-project --clean      # warm: clean build tree, caches filled
buildpulse compare                                 # last two runs, stage by stage
buildpulse compare 20261105-183909-linux-arm64 20261105-184015-linux-arm64
```

Every run records its cache settings and the compiler-cache hit rate in `report.json`
(`meta.cache`, `meta.compiler_cache_stats`) and in the summary line, so timings are never
compared blind.

### Measured on the internal sample project

| Build | Cold (`--no-cache`) | Warm (`--clean`, caches filled) | Speed-up |
|-------|--------------------:|--------------------------------:|---------:|
| macOS host, Debug — `deps` (GTest) | 7.52 s | 0.35 s | 21.7× |
| macOS host, Debug — total | 9.34 s | 2.19 s | 4.3× |
| aarch64 cross in Docker — `deps` (GTest) | 23.48 s | 2.74 s | 8.6× |
| aarch64 cross in Docker — total | 34.22 s | 16.68 s | 2.1× |
| aarch64 cross, GitHub runner (`cache-benchmark` job) — `deps` | 14.64 s | 0.48 s | 30.5× |
| aarch64 cross, GitHub runner (`cache-benchmark` job) — total | 16.59 s | 2.01 s | 8.3× |
| Windows MSVC, GitHub runner — `deps` (GTest built from source vs. restored) ¹ | 34.66 s | 0.66 s | 52.5× |
| Windows MSVC, GitHub runner — total ¹ | 40.95 s | 21.02 s | 1.9× |

¹ First CI run with empty caches vs. a re-run with the Conan and sccache caches restored
(sccache hit 3/3). ConanCenter has no prebuilt GTest for MSVC 19.5x, so the cold run builds it.
The warm run's total is dominated by a 13 s first-time MSVC/CMake compiler detection on a fresh
Windows VM (in the cold run, Conan's GTest build had already paid that cost inside `deps`).

The compiler cache hit 3/3 compilations on all warm runs. The sample project is tiny, so the dependency layer
dominates; on a real code base the ccache share grows with the number of translation units.
In Docker on a Mac every stage pays ~0.5–3 s of `docker run` start-up under Rosetta, which is why
small stages such as `cache-zero` look slow there; on a Linux CI runner that overhead is far smaller.
With the Docker layer, Conan and ccache caches restored, the whole `linux-arm64` CI job dropped from
1 min 34 s to 50 s.
A manual `cache-benchmark` job in the `cross-arm64` workflow (Actions → cross-arm64 → Run workflow)
repeats the cold/warm comparison on a GitHub runner and writes the table to the job summary.

### Caching layers

| Layer | What it caches | Where | Status |
|-------|----------------|-------|--------|
| **Conan binary cache** | Prebuilt dependency packages (GTest here), keyed by settings: OS, arch, compiler, build type | `~/.cache/buildpulse/conan2/<env>/` (`CONAN_HOME`) | ✅ |
| **ccache / sccache** | Object files of the project's own sources, keyed by compiler + flags + source. ccache on Linux/macOS, sccache for MSVC | `~/.cache/buildpulse/{ccache,sccache}/<env>/` (`CCACHE_DIR` / `SCCACHE_DIR`), used via `CMAKE_<LANG>_COMPILER_LAUNCHER` | ✅ |
| **CMake incremental build** | The build tree: only changed files are rebuilt, configure results reused | `build/<preset>` or `--build-dir`; `--clean` / `--no-cache` bypass it | ✅ (CMake + Ninja) |
| **Docker layer cache** | The cross image (toolchain, sysroot, Conan, ccache) | Local Docker; in CI `type=gha` via `docker/build-push-action` | ✅ |
| **CI caches** | Conan and ccache/sccache directories between workflow runs | `actions/cache` in `ci.yml`, `cross-arm64.yml`, `windows-msvc.yml` | ✅ |

`<env>` is `host` or the Docker image name, so binaries from different toolchains never mix.
The cross image ships Conan profiles (`toolchains/conan/linux-armv8`, `linux-x86_64`) through
`CONAN_DEFAULT_PROFILE` / `CONAN_DEFAULT_BUILD_PROFILE`; the host profile chains the aarch64 CMake
toolchain file via `tools.cmake.cmaketoolchain:user_toolchain`.

### Related techniques not used (yet)

| Technique | What it adds | When to reach for it |
|-----------|--------------|----------------------|
| **Conan remote** (Artifactory, `conan_server`) | Share dependency binaries across machines and CI: build once, upload, everyone downloads | A team or a CI fleet; the next step after the local cache |
| **sccache remote backends** | sccache is used locally (MSVC); it can also store to S3, GCS, Redis or the GitHub Actions cache | Shared compiler cache across a CI fleet |
| **ccache remote storage** | ccache ≥ 4.4 can also use an HTTP/Redis secondary store | Same goal as sccache while staying on ccache |
| **vcpkg binary caching** | vcpkg's equivalent of the Conan binary cache (files, NuGet, GHA) | Projects that use vcpkg instead of Conan |
| **Precompiled headers / unity builds** | `target_precompile_headers`, `CMAKE_UNITY_BUILD`: less repeated header parsing | Header-heavy C++ (Boost, Qt); speeds up cold builds too |
| **Bazel / remote execution** | Content-addressed action cache shared by everyone, distributed builds | Very large mono-repos; a different build system |

## Fix, don't just file: CI triage with Claude

A red build should end in a reviewed fix PR, not in a ticket that says "here is a log".
Two layers make that work:

**1. `buildpulse triage`: deterministic evidence.** Turns a failed run into a compact bundle:
category (`dependencies` / `configure` / `compile` / `link` / `test` / `command`), failing stage and
command (Docker wrapper stripped), environment, extracted diagnostics, failed tests, the source lines
each error points at (CI and container paths are mapped back to the local checkout), and the log
tail. Every build workflow writes it to the job summary and the `build-logs` artifact on failure.

```bash
buildpulse triage                    # newest local run, Markdown
buildpulse triage <run-id> --json    # for scripts and agents
```

An agent reading this bundle instead of a 10,000-line log gets the right context, uses far fewer
tokens, and starts from the same facts a person would.

**2. `.claude/skills/ci-triage`: the agent workflow, shared with the team.** A Claude Code skill
that any developer (or CI) can invoke: collect evidence (`gh run download` + `buildpulse triage`),
decide whether the failure is this change's fault or pre-existing on the base branch, classify and
decide if the fix is within reach, find the root cause across toolchains, reproduce with the same
preset/image, make the minimal fix (never by weakening tests or warnings), validate, open a PR
against the failing branch, watch every check, and hand over **without merging**. Team knowledge
lives next to it in `references/failure-patterns.md`.

**CI: `ci-autofix.yml`.** When `ci`, `cross-arm64` or `windows-msvc` fails, runs Claude Code
(`anthropics/claude-code-action`) with the skill. Opt-in: it does nothing until the repo has an
`ANTHROPIC_API_KEY` secret. Guardrails: same-repository branches only (no secrets on fork code),
never re-triggers on `fix/ci-*` branches, and it can open PRs and issues but never merges.

### Worked example (PRs #1–#3)

| Step | What happened |
|------|---------------|
| Change | [#1](https://github.com/jzoscar/BuildPulse/pull/1) adds an SSE `_mm_prefetch` to `crc32` for speed |
| CI | Linux x64 ✅, **cross-arm64 ❌**, **windows-msvc ❌** |
| Triage, arm64 | Bundle: `compile`, stage `build`, `checksum.cpp:6 xmmintrin.h: No such file or directory`, source context mapped from `/home/runner/...` to `src/checksum.cpp` |
| Triage, Windows | No bundle (failed in pytest). `main` was red with the same failure → **pre-existing, not #1's fault**: triage printed `src\checksum.cpp` on Windows |
| Fix A | [#2](https://github.com/jzoscar/BuildPulse/pull/2) → `main`: paths via `as_posix()`, `mkdir -p build-logs`. All checks ✅ |
| Fix B | Reproduced locally in the cross image; [#3](https://github.com/jzoscar/BuildPulse/pull/3) → #1's branch: portable `prefetch()` (`__builtin_prefetch` / MSVC-only `_mm_prefetch`), no out-of-range pointers, new 4 KiB GTest. arm64 ✅ under QEMU |
| Validate | #2 + #3 combined on a temporary branch: `windows-msvc` ✅ (MSVC 19.51, 4/4 tests), linked on #3 |
| Hand over | Merge order #2 → main, main → feature, #3, #1. Merging is the owning team's call |

Two failures in one PR, two different root causes, each fixed at the right place: that distinction
is what the skill is for. Both lessons were added to `failure-patterns.md`.

## Supply chain: SBOM, SCA and SAST (EU Cyber Resilience Act)

`buildpulse scan` runs the supply-chain checks as recorded stages, like a build: every stage's
log, a `report.json` with component and finding counts, and the outputs in the run directory.

```bash
buildpulse scan                      # the configured project (native/)
buildpulse scan -C . --fail-on high  # the whole repo: C++ project + Python tooling + CI config
```

| Stage | Tool | Output | Gate |
|-------|------|--------|------|
| `lock` | `conan lock create` (only if the project uses Conan and has no `conan.lock`) | `conan.lock`, committed | — |
| `sbom` | Syft | `sbom.cdx.json` (CycloneDX) + `sbom.spdx.json` (SPDX), source name + `git describe` version | — |
| `sca` | Trivy on the SBOM | table in the log | fails at `--fail-on` severity and above (default `high`) |
| `sca-sarif` | Trivy on the SBOM | `sca.sarif`, all severities | — |
| `sast` | Semgrep (`p/c`, `p/python`) | `sast.sarif` | fails on ERROR-severity findings |

All stages run even if one fails, so a single report lists every finding. `buildpulse build` uses
the committed `conan.lock`, so the dependencies that are built are exactly the ones in the SBOM.

**CI: `security.yml`** runs on every push/PR **and weekly**, because new CVEs are published against
code that has not changed. It runs `buildpulse scan -C .`, `trivy config` on the Dockerfile and
workflows (report only), uploads `sca.sarif` / `sast.sarif` to GitHub code scanning, keeps the SBOMs
as artifacts, and runs **CodeQL** for C++ (observing a real `buildpulse build`) and Python.

### Why it matters here (EU CRA)

A networked sensor like a Gocator is a "product with digital elements" under the CRA (Regulation
(EU) 2024/2847). Reporting of actively exploited vulnerabilities applies from 11 September 2026; the
main obligations from 11 December 2027. For the build pipeline that means: an SBOM in a
machine-readable format (CycloneDX or SPDX) in the technical documentation for every release, known
vulnerabilities tracked against it for the whole support period, and fast answers to "are we
affected?" when a CVE lands (early warning within 24 h for exploited ones). The SBOM does not have
to be published, but it has to exist and be accurate per release.

### What this scan does not cover yet (and how to close it)

| Gap | Why it matters | Next step |
|-----|----------------|-----------|
| **Semgrep's C rules skip `.cpp` files** (it reported "0 findings" on C++ it never looked at) | A green SAST check that scanned nothing is worse than none | CodeQL `c-cpp` in `security.yml` (done); add `clang-tidy` (`bugprone-*`, `cert-*`) as a fast PR check |
| **Sysroot libraries are invisible**: glibc and libstdc++ from the bookworm sysroot are unpacked with `dpkg-deb -x`, so no package database records them | They are linked into the product, so they belong in its SBOM | Record the sysroot package list (name, version, purl) when building the image, merge it into the product SBOM, or scan the final firmware image / rootfs instead of the source tree |
| **Test-only dependencies are listed** (GTest is a `test_requires`) | Noise in the product SBOM; CycloneDX can mark scope | Generate the product SBOM from the Conan graph with scopes (`required` vs `excluded`), or drop test requirements |
| **Vendored / copied C++ code has no manifest** | Syft finds packages by manifests, not by copied source | Keep third-party code in Conan, or declare vendored code in a manifest |
| **CI actions are referenced by tag** (`actions/checkout@v7`; 27 of them in the SBOM) | Tags are mutable; a compromised action runs with the repo's token | Pin actions to commit SHAs, update them with Dependabot/Renovate |
| **No VEX** | A CVE in a function we never call is still reported as affected | Publish VEX statements (CycloneDX VEX / OpenVEX) next to the SBOM |
| **Artifacts are not signed** | The SBOM and binaries should be verifiably ours | Sign with Sigstore/cosign or an HSM-backed key; attach SLSA provenance to releases |

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
├── latest -> 20261105-180129-host-debug
└── latest.txt                   newest run id (works where symlinks don't, e.g. Windows)
```

- **Default log dir:** `.buildpulse/runs/` under the directory you run `buildpulse` from. Inside
  this repo, that is `<repo>/.buildpulse/runs/` (set by `buildpulse.toml`).
- **Choose a log dir:** `--log-dir <path>` on `build` or `run`.
- Logs are complete: stdout and stderr are merged in order, nothing is truncated, and each stage
  is framed by `==> [stage] <command>` and `<== [stage] exit N in Xs` lines.
- `.buildpulse/` is git-ignored.

## Analyze a log

```bash
buildpulse analyze-log latest                        # newest run's full.log
buildpulse analyze-log 20261105-181144-linux-arm64   # a run id or run directory
buildpulse analyze-log path/to/any.log --json
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

[cache]
dir = "~/.cache/buildpulse"
```

The `buildpulse.toml` in this repo points at `native/`, an **internal sample project used only to
test BuildPulse itself**. For real work, always pass `-C <your project>` (or use `run`). Without a
`buildpulse.toml` and without `-C`, the current directory is treated as the project.

## Next steps (designed, not built yet)

### Device test rigs: tests on real Gocators, not just QEMU

QEMU proves the aarch64 binary runs; it does not prove the product works on the sensor.
The plan for a rig behind CI:

- **Runner:** a self-hosted runner (or Bamboo remote agent) on a small Linux box in the lab, labelled
  by the hardware it can reach (`[self-hosted, linux, rig-gocator-2500]`). Jobs that need hardware
  ask for the label; everything else stays on cloud runners. A Raspberry Pi (bookworm, same glibc as
  our sysroot) is a cheap stand-in for developing the flow.
- **Flow:** `cross-arm64` publishes the build artifact → the rig job downloads it, **checks out a
  device** (lock), flashes or deploys, waits for health (boot, version endpoint), runs the on-device
  GTest binary and pytest/Jest end-to-end suites over the network, collects device logs, and
  **always** releases the device and restores a known-good image.
- **Results** go through buildpulse like any run: stage logs, `report.json`, and a triage bundle on
  failure, with the device id and firmware version in the environment.
- **Telling device faults from code faults:** health check before the test (fail as `infrastructure`,
  not `test`), a known-good build as control, retries only for infrastructure failures, and
  quarantining a device that fails its health check twice. Flaky tests are tracked, not retried away.
- **Capacity:** a pool of devices per product family, a queue with timeouts, and a dashboard of rig
  utilisation and failure causes.

### Bamboo → Bitbucket Pipelines (and how this repo maps to both)

| GitHub Actions (here) | Bamboo | Bitbucket Pipelines |
|---|---|---|
| Workflow file in the repo | Plan (UI or Bamboo Specs in Java/YAML) | `bitbucket-pipelines.yml` in the repo |
| Job | Stage → Job (jobs in a stage run in parallel) | Step (`parallel:` groups) |
| Step | Task | Script line / Pipe |
| Hosted / self-hosted runner | Local / remote / elastic agent with capabilities | Atlassian cloud runner / self-hosted runner with labels |
| `actions/cache` | Agent-local workspace or external cache | `caches:` (built-in and custom) |
| `upload-artifact` | Shared artifacts between stages | `artifacts:` |
| Deployment environments | Deployment projects + environments | `deployment:` environments |
| `workflow_dispatch` / matrix | Manual stage / plan variables, plan branches | Custom pipelines / `parallel` steps |

Migration approach: keep the logic out of CI YAML, so it moves with no rewrite. That is why every job
here is a thin wrapper around `buildpulse build|scan|triage`. Then: Bamboo Specs in the repo first (plans
as code), move one product line's PR builds to Pipelines with self-hosted runners for the Docker and
MSVC builds, run both in parallel and compare results and timings, switch over, and keep the
hardware-rig plans on Bamboo agents until the rig runners are ported.

### Also next
- **Remote caches at team scale:** Conan remote (Artifactory) for dependency binaries, sccache/ccache
  remote storage for compiler output, so every runner starts warm.
- **Versioning and artifact publishing:** version from git tags, build metadata in `report.json`,
  publish binaries, SBOM and checksums together per release.
- **Fewer `docker run` start-ups:** one long-lived build container per run instead of one per stage.
- **Jest** for the TypeScript front end, reported through the same run format.

## Roadmap

| # | Feature | Status |
|---|---------|--------|
| 1 | Python `buildpulse` CLI + pytest: build any project, capture full logs | ✅ |
| 2 | ARM64 cross-compilation in Docker (GCC + sysroot + CMake toolchain file) | ✅ |
| 3 | Claude skill: CI log → root cause → fix PR (`buildpulse triage`, `ci-triage` skill, `ci-autofix`) | ✅ |
| 4 | Build caching: Conan binary cache, ccache, Docker/CI caches, cold-vs-warm compare | ✅ |
| 5 | Supply chain: SBOM (Syft), SCA (Trivy), SAST (Semgrep + CodeQL), weekly re-scan | ✅ |
| 6 | Windows runner with MSVC (+ sccache, buildpulse tested on Windows) | ✅ |
| 7 | Device test rigs | 📝 designed, see Next steps |
| 8 | Bamboo ↔ Bitbucket Pipelines ↔ GitHub Actions mapping and migration | 📝 designed, see Next steps |
