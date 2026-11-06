---
name: ci-triage
description: Triage a failed BuildPulse build or CI run (GitHub Actions run, PR check, or local `.buildpulse/runs` run), find the root cause, and — when the fix is within reach — open a fix PR and validate its branch build. Use when a build, cross-compile, MSVC build or test run fails, or when asked to "fix CI", "why is the build red", or "triage run <id>".
---

# CI triage: fix, don't just file

Goal: go from a red build to a reviewed fix PR. A ticket that only says "here is a log" is the
fallback, not the deliverable.

Work through the steps in order. Keep notes as you go: the PR description is built from them.

## 1. Collect the evidence

Never start from the raw log. Start from the triage bundle, which already holds the failing stage,
its command, the environment, the extracted diagnostics with source context, and the log tail.

**GitHub Actions run** (URL or id):

```bash
gh run view <run-id> --json workflowName,headBranch,headSha,conclusion,jobs \
  -q '{wf: .workflowName, branch: .headBranch, sha: .headSha, failed: [.jobs[] | select(.conclusion=="failure") | .name]}'
gh run download <run-id> -D .buildpulse/ci/<run-id>          # artifacts include build-logs/
buildpulse triage latest --log-dir .buildpulse/ci/<run-id>/<artifact>/build-logs
```

If the job failed before buildpulse ran (checkout, setup, Docker image build), there is no
bundle: read `gh run view <run-id> --log-failed` instead and go to step 2 with that.

**Local run:** `buildpulse triage latest` (or a run id from `.buildpulse/runs/`).

Use `--json` when you want to process it; the Markdown form is for people.

## 2. Classify, and decide whether the fix is within reach

| Category (from the bundle) | Typical root causes | Within reach? |
|---|---|---|
| `compile` | Code that only one toolchain rejects (arch intrinsics, MSVC vs GCC dialect, missing include that another stdlib pulls in transitively), new warning under `/W4` or `-Wall -Wextra` | Usually yes |
| `link` | Missing source in a target, wrong `target_link_libraries`, symbol only defined for some platforms, runtime library mismatch (`/MD` vs `/MT`) | Usually yes |
| `configure` | Toolchain file, preset, CMake policy/version, a package not found in the sysroot | Often yes |
| `dependencies` | Conan recipe/version not found, no binary for this profile, remote down | Config: yes. Remote outage: no, file it |
| `test` | Real regression, platform-dependent behaviour (endianness, `long` size, float), QEMU-only flake | Yes if the expected behaviour is clear; otherwise ask the owner |
| `command` / no bundle | Runner, network, Docker, disk, secrets | No: re-run once; if it repeats, file it with evidence |

See `references/failure-patterns.md` for patterns seen on this project's toolchains.

Out of reach (needs a product decision, an infrastructure owner, or credentials): stop here and
file an issue with the bundle (`gh issue create --title ... --body-file triage.md`). Say why it is
out of reach.

## 3. Find the root cause

- Read the source context in the bundle, then the surrounding code.
- Ask **why this toolchain/architecture and not the others**: compare with the jobs that passed
  (Linux x64 GCC, aarch64 cross GCC, Windows MSVC). The difference is usually the root cause.
- Find the change that introduced it: `git log --oneline origin/main..<head> -- <file>` and
  `git show <sha> -- <file>`.
- State the root cause in one or two sentences before touching code. A symptom ("line 14 does
  not compile") is not a root cause ("x86-only SSE4.2 intrinsic used unconditionally; aarch64
  has no `<nmmintrin.h>`").

## 4. Reproduce

Reproduce with the same preset/image the CI job used:

```bash
buildpulse build --preset linux-arm64 --docker buildpulse/cross-arm64   # aarch64 cross job
buildpulse build --preset host-release                                  # Linux x64 job (or host-debug)
```

MSVC cannot be reproduced on macOS/Linux: say so, and rely on the PR's `windows-msvc` check.
If it does not reproduce anywhere, suspect the environment (step 2, `command`) before the code.

## 5. Fix

- Branch from the failing head: `git switch -c fix/ci-<short-topic> <head-sha-or-branch>`.
- Make the smallest change that fixes the root cause and keeps every platform working.
- Fix the code or the build configuration, never the evidence. Do not:
  disable or skip tests, delete assertions, drop warning levels, add `-w` / `#pragma warning(disable)`
  to silence a real problem, pin to an older toolchain, or special-case CI.
- Match the surrounding style. Add a test if the failure exposed missing coverage.

## 6. Validate before pushing

Re-run the failing configuration and at least one other:

```bash
buildpulse build --preset linux-arm64 --docker buildpulse/cross-arm64 --clean
buildpulse build --clean
```

If buildpulse itself changed: `pytest -q && ruff check src tests`.

## 7. Open the PR and validate the branch build

```bash
git push -u origin fix/ci-<short-topic>
gh pr create --base <failing-branch> --head fix/ci-<short-topic> \
  --title "fix(<area>): <what was broken>" --body-file pr-body.md
gh pr checks <pr> --watch      # every workflow must be green, not just the one that failed
```

PR body template:

```markdown
## Failure
<workflow / job / run link>, stage `<stage>`, category `<category>`.
<the key diagnostic, one or two lines>

## Root cause
<why it failed, and why only on this toolchain/arch>

## Fix
<what changed and why it is the right layer to fix it>

## Validation
- [x] Reproduced locally with `<command>` (or: not reproducible on this host, because ...)
- [x] `<command>` now passes
- [ ] CI: linux-x64, cross-arm64, windows-msvc (this PR)

Triage bundle: <attached or linked>
```

If a check still fails, go back to step 1 with the new run. Do not stack speculative commits.

## 8. Hand over

Report: root cause, PR link, check status, anything not verified. **Do not merge and do not
approve**: the owning team reviews and merges. If CI is green and the owner asks you to merge, use
`gh pr merge --squash`.
