"""Small synthetic integration smoke test, never a model quality benchmark."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.services import environment, ROOT
import os
os.environ.update(environment())
from tradepilot.schema import AnalyzeRequest
from tradepilot.model import analyze_remote

docs=[{"id":"quote-demo","kind":"quote","name":"quote.txt","blocks":[{"id":"q1","text":"Deposit: 30%","location":"line 1"},{"id":"q2","text":"Balance due: 30 days","location":"line 2"}]},
      {"id":"contract-demo","kind":"contract","name":"contract.txt","blocks":[{"id":"c1","text":"Deposit: 0%","location":"line 1"},{"id":"c2","text":"Balance due: 90 days","location":"line 2"}]}]
records=[]
for task in ["extract","review","compare"]:
    started=time.monotonic()
    try:
        result=analyze_remote(AnalyzeRequest(task=task,documents=docs if task=="compare" else docs[-1:]),"http://127.0.0.1:8102")
        meaningful=(any(f.field=="deposit_percent" and f.value=="0" for f in result.facts) if task=="extract" else
                    any(f.kind=="business_risk" for f in result.findings) if task=="review" else
                    result.comparison=="different" and bool(result.findings))
        invalid_evidence=any(x.startswith("已拒绝") or "标准化失败" in x for x in result.limitations)
        records.append({"task":task,"success":not invalid_evidence and meaningful,"seconds":time.monotonic()-started,"result":result.model_dump()})
    except Exception as exc:
        records.append({"task":task,"success":False,"seconds":time.monotonic()-started,"error":str(exc)[:500]})
out=ROOT/".data/model-smoke.json";out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps({"benchmark":False,"synthetic":True,"records":records},ensure_ascii=False,indent=2))
print(json.dumps([{k:v for k,v in r.items() if k!="result"} for r in records],ensure_ascii=False))
raise SystemExit(0 if all(r["success"] for r in records) else 1)
