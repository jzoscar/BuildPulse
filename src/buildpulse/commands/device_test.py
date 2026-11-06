"""Test a firmware build on a real (or simulated) device borrowed from a LabForge rig pool.

Stages, recorded like any other run:
  checkout   labforge rig checkout   borrow a healthy device; LabForge health-checks it first
  flash      labforge rig flash      install this build (version + sha256) and wait until it runs
  verify     labforge rig check      the device is healthy and runs exactly this build
  test       <--test-cmd>            optional on-device tests, with LABFORGE_DEVICE_* in the env
  release    labforge rig release    always return the device (it is power-cycled to a known state)

The result sent back to LabForge, and the triage category, separate the two kinds of failure:
checkout / flash failing is the lab's problem (`infra-failed`); the build not coming up healthy
or the tests failing is the code's (`failed`).

LabForge keeps the device and BMC credentials; this command only needs its URL and API token
(LABFORGE_SERVER, LABFORGE_API_TOKEN), and the `labforge` CLI on PATH.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from buildpulse.runner import Recorder, RunReport

INFRA_STAGES = ("checkout", "flash")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def result_of(report: RunReport) -> str:
    """What to report to LabForge for the stages run so far (release not included)."""
    failed = next((s.name for s in report.stages if s.returncode != 0), None)
    if failed is None:
        return "passed"
    return "infra-failed" if failed in INFRA_STAGES else "failed"


def run(
    pool: str,
    firmware: Path,
    version: str,
    log_dir: Path,
    *,
    holder: str,
    test_cmd: list[str] | None = None,
    project_dir: Path | None = None,
    labforge: str | list[str] = "labforge",
    ttl: int = 1800,
    echo: bool = True,
) -> RunReport:
    project_dir = project_dir or Path.cwd()
    lf = [labforge] if isinstance(labforge, str) else list(labforge)  # CLI, or e.g. [python, script]
    recorder = Recorder(log_dir, kind="device-test", label=f"device-{pool}", project_dir=project_dir,
                        echo=echo)
    run_dir = recorder.run_dir
    lease_file = run_dir / "lease.json"
    digest = sha256(firmware)
    meta = {"pool": pool, "firmware": {"version": version, "file": str(firmware), "sha256": digest,
                                        "size": firmware.stat().st_size},
            "labforge": os.environ.get("LABFORGE_SERVER", "http://127.0.0.1:8000")}

    checkout = recorder.stage("checkout", [*lf, "rig", "checkout", "--pool", pool, "--holder", holder,
                                           "--ttl", str(ttl), "--output", "text", "--write", str(lease_file)],
                              cwd=project_dir)
    if checkout.returncode != 0 or not lease_file.is_file():
        return recorder.finish(**meta, result="infra-failed", device=None)

    lease = json.loads(lease_file.read_text())
    lease_id = str(lease["leaseId"])
    meta["device"] = {k: lease.get(k) for k in ("device", "address", "host", "endpoints", "platform", "labels")}
    meta["lease_id"] = lease["leaseId"]

    flashed = recorder.stage("flash", [*lf, "rig", "flash", lease_id, "--version", version,
                                       "--artifact", str(firmware)], cwd=project_dir)
    if flashed.returncode == 0:
        verified = recorder.stage("verify", [*lf, "rig", "check", lease_id, "--expect-version", version,
                                             "--artifact", str(firmware)], cwd=project_dir)
        if verified.returncode == 0 and test_cmd:
            endpoints = lease.get("endpoints") or {}
            recorder.stage("test", test_cmd, cwd=project_dir, env={
                "LABFORGE_LEASE_ID": lease_id,
                "LABFORGE_DEVICE": str(lease.get("device") or ""),
                "LABFORGE_DEVICE_HOST": str(lease.get("host") or ""),
                "LABFORGE_DEVICE_HTTP": endpoints.get("http", ""),
            })

    result = result_of(recorder.report)
    recorder.stage("release", [*lf, "rig", "release", lease_id, "--result", result], cwd=project_dir)
    return recorder.finish(**meta, result=result)
