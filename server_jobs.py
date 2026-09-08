"""Local workbench job launcher. No shell interpolation or remote code execution."""
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.audit import write_json
from engine.pipeline import project_lock

ROOT = Path(__file__).resolve().parent
JOBS = ROOT / "artifacts" / "jobs"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["manual", "hybrid", "llm"] = "hybrid"
    max_symbols: int = Field(default=600, ge=0, le=6000)
    max_structures: int = Field(default=4, ge=1, le=1000)
    workers: int = Field(default=4, ge=1, le=8)
    full_grid: bool = False
    evolution_budget: int = Field(default=140, ge=0, le=930)
    auto_evolve: bool = True
    engineering: bool = True
    discovery: bool = False
    bayes: bool = False
    data_profile: Literal["full", "daily"] = "full"
    industry_policy: Literal["strict", "quarantine"] = "strict"
    industry_source: Literal["exact_intervals", "rqdata_daily"] = "exact_intervals"
    auction_policy: Literal["strict", "quarantine"] | None = None

    @model_validator(mode="after")
    def supported_seed_count(self):
        if not self.full_grid and self.provider == "manual" and self.max_structures > 4:
            raise ValueError("Fixed baselines contain four structures")
        if 0 < self.max_symbols < 100:
            raise ValueError("Select all symbols (0) or at least 100")
        return self


def process_alive(pid: int | None) -> bool:
    """Check process liveness without signalling Windows processes.

    Args:
        pid: Recorded positive process ID, or None for an incomplete launch.
    Returns:
        bool: Whether the process exists; access denial is conservatively alive.
    """
    if pid is None:
        return False
    if pid <= 0:
        raise ValueError("Process ID must be positive")
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:
            return False
        if error == 5:
            return True
        raise ctypes.WinError(error)
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)


def list_jobs():
    JOBS.mkdir(parents=True, exist_ok=True)
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(JOBS.glob("*.json"), reverse=True)][:30]


def launch(request: RunRequest):
    JOBS.mkdir(parents=True, exist_ok=True)
    with project_lock(ROOT / "artifacts"):
        for job in list_jobs():
            if job["status"] in {"QUEUED", "RUNNING"}:
                if process_alive(job.get("pid")):
                    raise RuntimeError("A workbench job is already active")
        job_id = datetime.now(UTC).strftime("job-%Y%m%dT%H%M%S-") + uuid4().hex[:6]
        record = {"id": job_id, "status": "QUEUED", "options": request.model_dump(),
                  "created_at": datetime.now(UTC).isoformat()}
        write_json(JOBS / (job_id + ".json"), record)
        with (JOBS / (job_id + ".log")).open("w") as log:
            process = subprocess.Popen([sys.executable, str(ROOT / "server_jobs.py"),
                                        "--worker", job_id], cwd=ROOT, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        record["pid"] = process.pid
        write_json(JOBS / (job_id + ".json"), record)
    (JOBS / (job_id + ".ready")).touch()
    return record


def worker(job_id):
    if not job_id.startswith("job-") or any(c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-" for c in job_id):
        raise ValueError("Invalid job ID")
    import time
    ready = JOBS / (job_id + ".ready")
    for _ in range(100):
        if ready.exists():
            break
        time.sleep(.05)
    else:
        raise RuntimeError("Job launch handshake not published")
    path = JOBS / (job_id + ".json")
    record = json.loads(path.read_text(encoding="utf-8"))
    options = RunRequest.model_validate(record["options"])
    record.update(status="RUNNING", pid=os.getpid())
    write_json(path, record)
    args = [sys.executable, "run_engine.py", "--run-id", job_id,
            "--provider", options.provider, "--max-symbols", str(options.max_symbols),
            "--max-structures", str(options.max_structures), "--workers", str(options.workers),
            "--industry-policy", options.industry_policy, "--industry-source", options.industry_source,
            "--data-profile", options.data_profile]
    if options.full_grid:
        args.extend(["--full-grid", "--evolution-budget", str(options.evolution_budget)])
    if not options.auto_evolve:
        args.append("--no-auto-evolve")
    if options.auction_policy:
        args.extend(["--auction-policy", options.auction_policy])
    if options.engineering:
        args.append("--engineering")
    if options.discovery:
        args.append("--discovery")
    if options.bayes:
        args.append("--bayes")
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    result = subprocess.run(args, cwd=ROOT, env=env, check=False)
    record.update(status="COMPLETED" if result.returncode == 0 else "FAILED",
                  exit_code=result.returncode, finished_at=datetime.now(UTC).isoformat())
    write_json(path, record)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--worker":
        raise SystemExit("Use the local API to launch jobs")
    worker(sys.argv[2])
