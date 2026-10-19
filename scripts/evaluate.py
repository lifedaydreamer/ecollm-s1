"""Evaluate reviewed text tasks; model comparisons must share the same frozen input file."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tradepilot.schema import AnalyzeRequest
from tradepilot.model import analyze_remote


def main():
    p=argparse.ArgumentParser();p.add_argument("data",type=Path);p.add_argument("--endpoint",required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    rows=[json.loads(x) for x in a.data.read_text().splitlines() if x.strip()]
    if any(r.get("review_status")!="approved" or r.get("split")!="test" or not r.get("second_reviewer") for r in rows):
        raise SystemExit("独立评测仅接受已复核、封存的 test 样本")
    predictions=[]; tp=fp=fn=correct=valid=0; started=time.time()
    for r in rows:
        try:
            result=analyze_remote(AnalyzeRequest.model_validate(r["input"]),a.endpoint)
            valid+=1
            expected={(f["kind"],f["title"]) for f in r["candidate_output"].get("findings",[])}
            actual={(f.kind,f.title) for f in result.findings}
            tp+=len(expected&actual);fp+=len(actual-expected);fn+=len(expected-actual)
            correct+=result.comparison==r["candidate_output"]["comparison"]
            predictions.append({"id":r["id"],"result":result.model_dump()})
        except Exception as exc:predictions.append({"id":r["id"],"error":type(exc).__name__})
    report={"input_sha256":hashlib.sha256(a.data.read_bytes()).hexdigest(),"n":len(rows),"schema_valid_rate":valid/max(len(rows),1),
        "comparison_accuracy":correct/max(len(rows),1),"exact_finding_f1":2*tp/max(2*tp+fp+fn,1),"elapsed_seconds":time.time()-started,
        "metric_note":"Exact title matching is a diagnostic metric, not semantic risk Macro-F1; human adjudication still required.","predictions":predictions}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
