"""Synthetic deployed-system integration, not a held-out effectiveness benchmark."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.services import ROOT, environment
import httpx

smoke=json.loads((ROOT/".data/model-smoke.json").read_text())
if not all(r["success"] for r in smoke["records"]):
    raise SystemExit("模型最小接口测试未通过，保持规则基线，不启用模型。")
path=ROOT/".runtime/env.json"
config=json.loads(path.read_text())
config.pop("TRADEPILOT_DEBUG_MODEL",None)
config["TRADEPILOT_MODEL_URL"]="http://127.0.0.1:8102"
config["TRADEPILOT_MODEL_NAME"]="Qwen3-4B-Instruct-2507-base"
path.write_text(json.dumps(config))
for action in ["stop","start"]:
    subprocess.run([sys.executable,str(ROOT/"scripts/services.py"),action,"api"],check=True)
client=httpx.Client(base_url="http://127.0.0.1:8100",headers={"X-API-Key":config["TRADEPILOT_TOKEN"]},timeout=20)
for _ in range(20):
    try:
        if client.get("/health").json().get("model_configured"):break
    except httpx.HTTPError:pass
    time.sleep(1)
else:raise SystemExit("API did not restart")
case=client.post("/demo?variant=conflict").raise_for_status().json()
created=client.post(f"/cases/{case['id']}/runs").raise_for_status().json()
run_path=f"/cases/{case['id']}/runs/{created['id']}"
started=time.monotonic()
for _ in range(180):
    run=client.get(run_path).raise_for_status().json()
    if run["status"] not in {"queued","running"}:break
    time.sleep(2)
else:raise SystemExit("Review exceeded the integration timeout; check persisted run")
if run["status"]!="awaiting_review":raise SystemExit(json.dumps(run.get("error")))
if not any(f["origin"]=="model" for f in run["findings"]):
    raise SystemExit("No verified model findings were returned; did not count as semantic success")
if client.post(run_path+"/approve",json={}).status_code!=409:
    raise SystemExit("Approval gate failed")
for f in run["findings"]:
    client.post(run_path+"/decisions/"+f["id"],json={"action":"accept","reason":"虚构集成案例：仅用于验证人工决策与归档流程，不代表真实合同接受。"}).raise_for_status()
approved=client.post(run_path+"/approve",json={"acknowledge_limitations":True,"reason":"虚构案例工程验收，已阅读覆盖范围；不作为模型质量或真实业务效果证据。"}).raise_for_status().json()
assert approved["status"]=="approved"
exports={}
for fmt in ["json","txt","pdf","docx"]:
    response=client.get(run_path+"/export/"+fmt).raise_for_status()
    exports[fmt]={"status":response.status_code,"bytes":len(response.content)}
report={"benchmark":False,"synthetic":True,"case_id":case["id"],"run_id":created["id"],
        "status":approved["status"],"seconds":time.monotonic()-started,"rule_findings":sum(f["origin"]=="rule" for f in run["findings"]),
        "model_findings":sum(f["origin"]=="model" for f in run["findings"]),"limitations":run.get("limitations",[]),"exports":exports}
(ROOT/".data/integration-result.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
