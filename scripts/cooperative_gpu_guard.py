"""Explicit opt-in shared GPU execution. Only this guard's own child group may be stopped."""
import argparse
import csv
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


def query(kind, fields):
    output = subprocess.check_output(["nvidia-smi", f"--query-{kind}={fields}", "--format=csv,noheader,nounits"],
                                     text=True, timeout=15)
    return list(csv.reader(output.splitlines(), skipinitialspace=True))


def inspect(uuid, existing_pids, max_job_mib=24576, reserve_mib=16384, startup=False, allow_busy=False):
    gpu = next((r for r in query("gpu", "uuid,memory.total,memory.free,utilization.gpu") if r[0] == uuid), None)
    if gpu is None: raise RuntimeError("Allocated GPU UUID is unavailable; never switch devices")
    processes = [r for r in query("compute-apps", "gpu_uuid,pid,used_gpu_memory") if r[0] == uuid]
    if startup and any(int(r[1]) not in existing_pids for r in processes):
        raise RuntimeError("An unapproved GPU process appeared before launch")
    total, free, util = map(float, gpu[1:])
    job_usage = sum(float(r[2]) for r in processes if int(r[1]) not in existing_pids)
    if startup and (free < max_job_mib + reserve_mib + 2048 or (util > 5 and not allow_busy)):
        raise RuntimeError("Shared GPU does not have the required idle utilization and free-memory margin")
    if not startup and (free < reserve_mib or job_usage > max_job_mib):
        raise RuntimeError("Shared GPU memory limit approached; stop only this task")
    return {"uuid": uuid, "free_mib": free, "utilization": util, "new_process_memory_mib": job_usage,
            "existing_pids": sorted(existing_pids), "max_task_mib": max_job_mib, "reserve_mib": reserve_mib}


def starttime(pid):
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]


def stop_own_group(child, saved_start):
    if child.poll() is not None: return
    try:
        proc = Path(f"/proc/{child.pid}")
        if proc.stat().st_uid != os.getuid() or starttime(child.pid) != saved_start or os.getpgid(child.pid) != child.pid:
            raise RuntimeError("Child ownership changed; refusing to signal any group")
        os.killpg(child.pid, signal.SIGTERM)
        try: child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if starttime(child.pid) == saved_start and os.getpgid(child.pid) == child.pid:
                os.killpg(child.pid, signal.SIGKILL)  # Only the verified group created by this invocation.
            child.wait(timeout=10)
    except ProcessLookupError:
        pass


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gpu", required=True); p.add_argument("--existing-pid", type=int, action="append", default=[])
    p.add_argument("--snapshot-existing", action="store_true", help="Explicitly authorized sharing: snapshot current occupants, then require three stable idle checks")
    p.add_argument("--allow-busy-shared", action="store_true", help="Explicitly authorized compute sharing; retain memory cap, reserve and stable occupant checks")
    p.add_argument("--max-job-mib", type=int, default=24576); p.add_argument("--reserve-mib", type=int, default=16384)
    p.add_argument("command", nargs=argparse.REMAINDER); a = p.parse_args()
    if not re.fullmatch(r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", a.gpu): p.error("Exact GPU UUID required")
    if not 0 < a.max_job_mib <= 24576 or a.reserve_mib < 16384: p.error("Task cap must be <=24GiB and reserve >=16GiB")
    command = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not command: p.error("An explicit child command is required")
    lock_path = Path(os.getenv("TRADEPILOT_GPU_LOCK_DIR", str(Path(__file__).resolve().parents[1] / ".data"))) / ("gpu-" + a.gpu + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        existing = set(a.existing_pid)
        if a.snapshot_existing:
            existing = {int(r[1]) for r in query("compute-apps", "gpu_uuid,pid,used_gpu_memory") if r[0] == a.gpu}
        elif not existing:
            p.error("Choose explicit sharing snapshot or supply the existing PID set")
        for sample in range(3):
            snapshot = inspect(a.gpu, existing, a.max_job_mib, a.reserve_mib, startup=True, allow_busy=a.allow_busy_shared)
            print(json.dumps({"shared_gpu_preflight": sample + 1, **snapshot}), flush=True)
            if sample < 2: time.sleep(2)
        # Leave CUDA context/library overhead below the user's 24GiB total limit.
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": a.gpu, "OMP_NUM_THREADS": "2",
               "TOKENIZERS_PARALLELISM": "false", "HF_HUB_DISABLE_TELEMETRY": "1",
               "TRADEPILOT_MAX_ALLOCATOR_GIB": "22"}
        os.nice(10)
        child = subprocess.Popen(command, env=env, start_new_session=True)
        saved_start = starttime(child.pid); stopped = False
        def requested_stop(*_):
            nonlocal stopped
            stopped = True
        signal.signal(signal.SIGTERM, requested_stop); signal.signal(signal.SIGINT, requested_stop)
        try:
            while child.poll() is None:
                if stopped: raise RuntimeError("Own manager requested shutdown")
                snapshot = inspect(a.gpu, existing, a.max_job_mib, a.reserve_mib)
                print(json.dumps({"shared_gpu_monitor": snapshot}), flush=True)
                for _ in range(5):
                    if stopped or child.poll() is not None: break
                    time.sleep(1)
            return child.returncode
        finally:
            stop_own_group(child, saved_start)


if __name__ == "__main__":
    try: sys.exit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print("SHARED_GPU_GUARD_REFUSED: " + str(exc), file=sys.stderr); sys.exit(75)
