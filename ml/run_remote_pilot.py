"""Pause only the verified own model manager, train under its guard, then restore it."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def process_alive(pid, expected_start):
    try:
        stat=Path(f"/proc/{pid}/stat").read_text().rsplit(")",1)[1].split()
        return stat[0] != "Z" and stat[19] == expected_start
    except (FileNotFoundError, ProcessLookupError):
        return False


def main():
    p=argparse.ArgumentParser();p.add_argument("--project",type=Path,required=True);p.add_argument("--gpu",required=True)
    p.add_argument("--model",type=Path,required=True);p.add_argument("--data",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True);p.add_argument("--config",type=Path,required=True)
    p.add_argument("--suite", action="store_true"); p.add_argument("--old-adapter", type=Path)
    p.add_argument("--baseline-suite", type=Path)
    p.add_argument("--release-wait-seconds", type=int, default=180)
    p.add_argument("--shared-existing-pid", type=int)
    p.add_argument("--shared-snapshot", action="store_true")
    p.add_argument("--allow-busy-shared", action="store_true")
    p.add_argument("--restore-model", action="store_true")
    a=p.parse_args();project=a.project.resolve();root=Path(__file__).resolve().parents[1]
    if a.output.exists() and any(a.output.iterdir()):raise SystemExit("Experiment output must be new")
    if a.suite and (not a.old_adapter or not a.old_adapter.is_dir()): raise SystemExit("Suite requires the actual V1 Adapter")
    runtime=root/".runtime";runtime.mkdir(exist_ok=True)
    def state(phase,**values):
        value={"phase":phase,"gpu_uuid":a.gpu,**values}
        (runtime/"pilot-state.json").write_text(json.dumps(value,indent=2))
        print(json.dumps(value),flush=True)
    record=project/".runtime/model.pid.json"
    restore=a.restore_model
    own_running=False
    own_workers={}
    if record.exists():
        saved=json.loads(record.read_text());pid=saved["pid"]
        proc=Path(f"/proc/{pid}")
        if proc.exists() and (proc/"stat").read_text().rsplit(")",1)[1].split()[0] != "Z":
            stat=(proc/"stat").read_text().rsplit(")",1)[1].split()
            cmd=(proc/"cmdline").read_bytes().decode().split("\0")
            if stat[19]!=saved["starttime"] or proc.stat().st_uid!=os.getuid() or (proc/"cwd").resolve()!=project:
                raise SystemExit("Recorded model process ownership not verified; nothing stopped")
            if not any(str(project/"scripts"/name) in cmd for name in ("gpu_guard.py", "cooperative_gpu_guard.py")) or "--gpu" not in cmd or cmd[cmd.index("--gpu")+1]!=a.gpu:
                raise SystemExit("Own model manager GPU does not match; nothing stopped")
            restore=True; own_running=True
            # In explicit sharing mode wait only for this project's verified workers.
            # NVIDIA host PIDs may be invisible in a container and are never signal targets.
            if a.shared_snapshot:
                for candidate in Path("/proc").iterdir():
                    if not candidate.name.isdigit(): continue
                    try:
                        worker_cmd=(candidate/"cmdline").read_bytes().decode().split("\0")
                        worker_stat=(candidate/"stat").read_text().rsplit(")",1)[1].split()
                        if (candidate.stat().st_uid == os.getuid() and (candidate/"cwd").resolve() == project
                            and "uvicorn" in worker_cmd and "tradepilot.model_server:app_factory" in worker_cmd
                            and worker_stat[0] != "Z"):
                            own_workers[int(candidate.name)]=worker_stat[19]
                    except (FileNotFoundError, PermissionError, ProcessLookupError):
                        continue
    python=project/".venv/bin/python"
    try:
        if own_running:
            (runtime/"pilot-own-workers.json").write_text(json.dumps({"manager":saved,"workers":own_workers},indent=2))
            state("pausing_verified_own_model")
            stopped=subprocess.run([str(python),str(project/"scripts/services.py"),"stop","model"],cwd=project)
            if stopped.returncode:
                state("own_manager_graceful_shutdown_still_pending",pid=pid)

            # A manager can exit before its worker's CUDA context has disappeared.
            # Wait only; never signal a process discovered through nvidia-smi.
            attempts = max(16, a.release_wait_seconds // 2)
            for attempt in range(attempts):
                if a.shared_snapshot:
                    busy=[pid] if process_alive(pid,saved["starttime"]) else []
                    for worker_pid, worker_start in own_workers.items():
                        try:
                            stat=Path(f"/proc/{worker_pid}/stat").read_text().rsplit(")",1)[1].split()
                            if stat[19] == worker_start and stat[0] != "Z": busy.append(worker_pid)
                        except (FileNotFoundError, ProcessLookupError):
                            continue
                else:
                    output=subprocess.check_output(["nvidia-smi","--query-compute-apps=gpu_uuid,pid","--format=csv,noheader"],text=True,timeout=15)
                    busy=[line for line in output.splitlines() if line.split(",")[0].strip()==a.gpu
                          and (not a.shared_existing_pid or int(line.split(",")[1]) != a.shared_existing_pid)]
                if not busy:break
                state("waiting_for_device_release",remaining_processes=len(busy),attempt=attempt+1)
                if attempt==attempts-1:raise RuntimeError("Device still has a compute process; no training launched")
                time.sleep(2)
        state("resource_guard_then_pilot")
        env={**os.environ,"PYTHONPATH":str(root),"OMP_NUM_THREADS":"2","HF_HUB_OFFLINE":"1","WANDB_DISABLED":"true"}
        guard=[str(project/"scripts/gpu_guard.py"),"--gpu",a.gpu,"--min-free-mib","40000"]
        if a.shared_existing_pid or a.shared_snapshot:
            guard=[str(root/"scripts/cooperative_gpu_guard.py"),"--gpu",a.gpu]
            guard += ["--snapshot-existing"] if a.shared_snapshot else ["--existing-pid",str(a.shared_existing_pid)]
            if a.allow_busy_shared: guard += ["--allow-busy-shared"]
            env["TRADEPILOT_GPU_LOCK_DIR"]=str(project/".data")
            env["TRADEPILOT_MAX_ALLOCATOR_GIB"]="22"
            state("explicit_shared_gpu_authorization",existing_pid=a.shared_existing_pid,task_cap_mib=24576,allocator_cap_gib=22,reserve_mib=16384)
        command=[str(project/".model-venv/bin/python"),*guard,"--",
                 str(project/".model-venv/bin/python"),str(root/"ml"/("run_clause_suite.py" if a.suite else "train_clause_pilot.py")),"--model",str(a.model),"--data",str(a.data),"--output",str(a.output),"--config",str(a.config)]
        if a.suite: command += ["--old-adapter", str(a.old_adapter)]
        if a.suite and a.baseline_suite: command += ["--baseline-suite", str(a.baseline_suite)]
        result=subprocess.run(command,cwd=root,env=env)
        state("pilot_finished",returncode=result.returncode)
    finally:
        if restore and own_running and process_alive(pid,saved["starttime"]):
            state("restore_deferred_own_manager_still_stopping",pid=pid)
        elif restore:
            state("restoring_original_own_model")
            if a.shared_existing_pid or a.shared_snapshot:
                import importlib.util
                import shutil
                spec=importlib.util.spec_from_file_location("original_services",project/"scripts/services.py")
                services=importlib.util.module_from_spec(spec);spec.loader.exec_module(services)
                # Preserve the business application; add only the explicitly opted-in resource utility.
                copied=project/"scripts/cooperative_gpu_guard.py"
                shutil.copyfile(root/"scripts/cooperative_gpu_guard.py",copied)
                env=services.environment();env["TRADEPILOT_MODEL_PATH"]=str(a.model)
                env["TRADEPILOT_MODEL_MEMORY_FRACTION"]="0.275"
                env["TRADEPILOT_GPU_LOCK_DIR"]=str(project/".data")
                sharing=["--snapshot-existing"] if a.shared_snapshot else ["--existing-pid",str(a.shared_existing_pid)]
                if a.allow_busy_shared: sharing += ["--allow-busy-shared"]
                cmd=[str(project/".model-venv/bin/python"),str(copied),"--gpu",a.gpu,*sharing,"--",
                     str(project/".model-venv/bin/python"),"-m","uvicorn","tradepilot.model_server:app_factory","--factory","--host","127.0.0.1","--port","8102","--workers","1"]
                with (project/".runtime/model.log").open("ab") as log:
                    proc=subprocess.Popen(cmd,cwd=project,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
                saved={"pid":proc.pid,"starttime":services.starttime(proc.pid),"resource_mode":"explicit_shared_24GiB","existing_pid":a.shared_existing_pid}
                (project/".runtime/model.pid.json").write_text(json.dumps(saved))
                state("restore_dispatched",pid=proc.pid,resource_mode="explicit_shared_24GiB")
            else:
                restored=subprocess.run([str(python),str(project/"scripts/services.py"),"start","model","--gpu",a.gpu],cwd=project)
                state("restore_dispatched",returncode=restored.returncode)
    return result.returncode


if __name__=="__main__":sys.exit(main())
