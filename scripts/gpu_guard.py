"""Fail closed on shared GPUs. Never signal, reset or evict any GPU process."""
import argparse
import csv
import fcntl
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time


def query(fields, kind="gpu"):
    output = subprocess.check_output(["nvidia-smi", f"--query-{kind}={fields}", "--format=csv,noheader,nounits"], text=True, timeout=15)
    return list(csv.reader(output.splitlines(), skipinitialspace=True))


def inspect_gpu(uuid, min_free=20000):
    gpu = next((r for r in query("uuid,memory.total,memory.free,utilization.gpu") if r[0] == uuid), None)
    if not gpu:
        raise RuntimeError("指定 GPU 不存在，禁止自动换卡")
    processes = [r for r in query("gpu_uuid,pid,used_gpu_memory", "compute-apps") if r[0] == uuid]
    if processes:
        raise RuntimeError(f"GPU 有 {len(processes)} 个计算进程，拒绝启动；不会终止任何进程")
    total, free, util = map(float, gpu[1:])
    if util > 5 or free < max(min_free, total * 0.15):
        raise RuntimeError(f"资源不足或正在使用：free={free} MiB util={util}%")
    return {"uuid": uuid, "total_mib": total, "free_mib": free, "utilization": util, "compute_processes": 0}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gpu", required=True, help="Exact GPU UUID, never a global index")
    p.add_argument("--min-free-mib", type=int, default=20000)
    p.add_argument("--min-disk-gib", type=int, default=50)
    p.add_argument("--samples", type=int, default=3)
    p.add_argument("command", nargs=argparse.REMAINDER)
    args = p.parse_args()
    if not re.fullmatch(r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", args.gpu):
        p.error("GPU 必须是 nvidia-smi 返回的完整 UUID")
    if args.samples < 3:
        p.error("至少检查三次资源快照")
    lock_path = Path(__file__).resolve().parents[1] / ".data" / ("gpu-" + args.gpu + ".lock")
    lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for i in range(args.samples):
            if shutil.disk_usage(lock_path.parent).free < args.min_disk_gib * 1024**3:
                raise RuntimeError("磁盘剩余空间低于预留值，拒绝启动")
            snapshot = inspect_gpu(args.gpu, args.min_free_mib)
            print(json.dumps(snapshot), flush=True)
            if i + 1 < args.samples:
                time.sleep(2)
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if command:
            env = {**os.environ, "CUDA_VISIBLE_DEVICES": args.gpu, "OMP_NUM_THREADS": "2",
                   "TOKENIZERS_PARALLELISM": "false", "HF_HUB_DISABLE_TELEMETRY": "1"}
            # The lock is held for this child only. It cannot reserve against unrelated users.
            os.nice(10)
            return subprocess.call(command, env=env)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
        print("RESOURCE_GUARD_REFUSED: " + str(exc), file=sys.stderr)
        sys.exit(75)
