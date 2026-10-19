"""Manage only this checkout's processes; bind all services to loopback."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/".runtime"
RUNTIME.mkdir(exist_ok=True)


def environment():
    path=RUNTIME/"env.json"
    if not path.exists():
        flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY
        fd=os.open(path,flags,0o600)
        with os.fdopen(fd,"w") as f:
            json.dump({"TRADEPILOT_TOKEN":secrets.token_urlsafe(32),"TRADEPILOT_MODEL_TOKEN":secrets.token_urlsafe(32)},f)
    value=json.loads(path.read_text())
    return {**os.environ,**value,"PYTHONPATH":str(ROOT),"TRADEPILOT_DATA":str(ROOT/".data"),
            "TRADEPILOT_API_URL":"http://127.0.0.1:8100","NEXT_TELEMETRY_DISABLED":"1",
            "OMP_NUM_THREADS":"2","TOKENIZERS_PARALLELISM":"false",
            "LANGCHAIN_TRACING_V2":"false","LANGSMITH_TRACING":"false",
            "PATH":str(RUNTIME/"node/bin")+os.pathsep+os.environ.get("PATH","")}


def starttime(pid):
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")",1)[1].split()[19]


def main():
    p=argparse.ArgumentParser();p.add_argument("action",choices=["start","status","stop"]);p.add_argument("service",choices=["api","web","model"]);p.add_argument("--gpu");a=p.parse_args()
    record=RUNTIME/(a.service+".pid.json")
    old=json.loads(record.read_text()) if record.exists() else None
    alive=False
    if old:
        try:
            pid=old["pid"]
            alive=(starttime(pid)==old["starttime"] and Path(f"/proc/{pid}").stat().st_uid==os.getuid()
                   and Path(f"/proc/{pid}/cwd").resolve().is_relative_to(ROOT))
        except (FileNotFoundError,PermissionError,ProcessLookupError): pass
    if a.action=="status":
        print(json.dumps({"service":a.service,"running":alive,"pid":old["pid"] if alive else None}));return
    if a.action=="stop":
        if alive:
            # This group was created by this manager and is checked against PID reuse and ownership.
            if os.getpgid(old["pid"])!=old["pid"]:raise SystemExit("Unexpected process group; refuse")
            os.killpg(old["pid"],signal.SIGTERM)
            for _ in range(100):
                try:
                    stat=Path(f"/proc/{old['pid']}/stat").read_text().rsplit(")",1)[1].split()
                    if stat[0]=="Z" or starttime(old["pid"])!=old["starttime"]:break
                except (FileNotFoundError,ProcessLookupError):break
                time.sleep(.1)
            else:raise SystemExit("Own service is still stopping; did not force kill")
            record.unlink(missing_ok=True)
            print("Stopped own service",a.service)
        return
    if alive:
        print("Already running",a.service);return
    env=environment()
    if a.service=="api":
        command=[str(ROOT/".venv/bin/python"),"-m","uvicorn","tradepilot.api:app_factory","--factory","--host","127.0.0.1","--port","8100","--workers","1"]
        cwd=ROOT
    elif a.service=="web":
        command=[str(RUNTIME/"node/bin/node"),str(ROOT/"web/node_modules/next/dist/bin/next"),"start","-H","127.0.0.1","-p","3100"]
        cwd=ROOT/"web"
    else:
        if not a.gpu:p.error("模型必须明确指定 --gpu UUID")
        env.setdefault("TRADEPILOT_MODEL_PATH","/data/yzh/tradepilot-models/Qwen3-4B-Instruct-2507")
        command=[str(ROOT/".model-venv/bin/python"),str(ROOT/"scripts/gpu_guard.py"),"--gpu",a.gpu,"--",str(ROOT/".model-venv/bin/python"),"-m","uvicorn","tradepilot.model_server:app_factory","--factory","--host","127.0.0.1","--port","8102","--workers","1"]
        cwd=ROOT
    with (RUNTIME/(a.service+".log")).open("ab") as log:
        proc=subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    record.write_text(json.dumps({"pid":proc.pid,"starttime":starttime(proc.pid)}))
    print("Started",a.service,"PID",proc.pid)


if __name__=="__main__":main()
