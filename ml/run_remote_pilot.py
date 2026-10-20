"""Pause only the verified own model manager, train under its guard, then restore it."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    p=argparse.ArgumentParser();p.add_argument("--project",type=Path,required=True);p.add_argument("--gpu",required=True)
    p.add_argument("--model",type=Path,required=True);p.add_argument("--data",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True);p.add_argument("--config",type=Path,required=True)
    a=p.parse_args();project=a.project.resolve();root=Path(__file__).resolve().parents[1]
    if a.output.exists() and any(a.output.iterdir()):raise SystemExit("Experiment output must be new")
    runtime=root/".runtime";runtime.mkdir(exist_ok=True)
    def state(phase,**values):
        value={"phase":phase,"gpu_uuid":a.gpu,**values}
        (runtime/"pilot-state.json").write_text(json.dumps(value,indent=2))
        print(json.dumps(value),flush=True)
    record=project/".runtime/model.pid.json"
    restore=False
    if record.exists():
        saved=json.loads(record.read_text());pid=saved["pid"]
        proc=Path(f"/proc/{pid}")
        if proc.exists():
            stat=(proc/"stat").read_text().rsplit(")",1)[1].split()
            cmd=(proc/"cmdline").read_bytes().decode().split("\0")
            if stat[19]!=saved["starttime"] or proc.stat().st_uid!=os.getuid() or (proc/"cwd").resolve()!=project:
                raise SystemExit("Recorded model process ownership not verified; nothing stopped")
            if str(project/"scripts/gpu_guard.py") not in cmd or "--gpu" not in cmd or cmd[cmd.index("--gpu")+1]!=a.gpu:
                raise SystemExit("Own model manager GPU does not match; nothing stopped")
            restore=True
    python=project/".venv/bin/python"
    try:
        if restore:
            state("pausing_verified_own_model")
            subprocess.run([str(python),str(project/"scripts/services.py"),"stop","model"],cwd=project,check=True)
            # A manager can exit before its worker's CUDA context has disappeared.
            # Wait only; never signal a process discovered through nvidia-smi.
            for attempt in range(16):
                output=subprocess.check_output(["nvidia-smi","--query-compute-apps=gpu_uuid,pid","--format=csv,noheader"],text=True,timeout=15)
                busy=[line for line in output.splitlines() if line.split(",")[0].strip()==a.gpu]
                if not busy:break
                state("waiting_for_device_release",remaining_processes=len(busy),attempt=attempt+1)
                if attempt==15:raise RuntimeError("Device still has a compute process; no training launched")
                time.sleep(2)
        state("resource_guard_then_pilot")
        env={**os.environ,"PYTHONPATH":str(root),"OMP_NUM_THREADS":"2","HF_HUB_OFFLINE":"1","WANDB_DISABLED":"true"}
        command=[str(project/".model-venv/bin/python"),str(project/"scripts/gpu_guard.py"),"--gpu",a.gpu,"--min-free-mib","40000","--",
                 str(project/".model-venv/bin/python"),str(root/"ml/train_clause_pilot.py"),"--model",str(a.model),"--data",str(a.data),"--output",str(a.output),"--config",str(a.config)]
        result=subprocess.run(command,cwd=root,env=env)
        state("pilot_finished",returncode=result.returncode)
    finally:
        if restore:
            state("restoring_original_own_model")
            restored=subprocess.run([str(python),str(project/"scripts/services.py"),"start","model","--gpu",a.gpu],cwd=project)
            state("restore_dispatched",returncode=restored.returncode)
    return result.returncode


if __name__=="__main__":sys.exit(main())
