"""Paired source-family bootstrap and error IDs, without retraining on the test set."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tradepilot.clause_task import score


def analyze(data, experiment, split):
    rows=[json.loads(line) for line in (data/(split+".jsonl")).read_text().splitlines() if line]
    def predictions(name):
        raw=json.loads((experiment/(name+"-"+split+"-predictions.json")).read_text())
        mapping={r["id"]:r for r in raw}
        if len(mapping)!=len(rows) or set(mapping)!={r["id"] for r in rows}:
            raise ValueError("Prediction IDs do not align with frozen inputs")
        return [mapping[r["id"]] for r in rows]
    base,tuned=predictions("base"),predictions("adapter")
    base_score,tuned_score=score(rows,base),score(rows,tuned)
    for name,computed in [("base",base_score),("adapter",tuned_score)]:
        recorded=json.loads((experiment/(name+"-"+split+"-metrics.json")).read_text())
        assert abs(computed["mean_evidence_token_f1"]-recorded["mean_evidence_token_f1"])<1e-10
    groups={}
    changes=[]
    quote_counts={name:{"emitted":0,"matched":0} for name in ("base","adapter")}
    for row,a,b in zip(rows,base,tuned):
        for name,prediction in [("base",a),("adapter",b)]:
            quotes=prediction.get("output",{}).get("evidence",[])
            quote_counts[name]["emitted"]+=len(quotes)
            quote_counts[name]["matched"]+=sum(q in row["input"]["text"] for q in quotes)
        old=score([row],[a])["mean_evidence_token_f1"]
        new=score([row],[b])["mean_evidence_token_f1"]
        delta=new-old
        groups.setdefault(row["source"]["family"],[]).append(delta)
        changes.append({"id":row["id"],"family":row["source"]["family"],"category":row["input"]["category"],
                        "base_token_f1":old,"adapter_token_f1":new,"delta":delta,"adapter_quotes_grounded":b.get("grounded",False),
                        "annotation_id":row["source"]["annotation_id"]})
    families=sorted(groups)
    randomizer=random.Random(20261020)
    estimates=[]
    for _ in range(2000):
        sampled=[value for _ in families for value in groups[randomizer.choice(families)]]
        estimates.append(sum(sampled)/len(sampled))
    estimates.sort()
    ci=[estimates[int(0.025*(len(estimates)-1))],estimates[int(0.975*(len(estimates)-1))]]
    for value in quote_counts.values():
        value["verified_quote_rate"]=value["matched"]/value["emitted"] if value["emitted"] else None
    return {"split":split,"n":len(rows),"source_families":len(families),"base":base_score,"adapter":tuned_score,
            "per_emitted_quote_grounding":quote_counts,
            "evidence_f1_gain":tuned_score["mean_evidence_token_f1"]-base_score["mean_evidence_token_f1"],
            "paired_source_family_bootstrap_95pct_ci":ci,"bootstrap_draws":2000,"bootstrap_seed":20261020,
            "input_sha256":hashlib.sha256((data/(split+".jsonl")).read_bytes()).hexdigest(),
            "improved_cases":sum(c["delta"]>0 for c in changes),"regressed_cases":sum(c["delta"]<0 for c in changes),
            "unchanged_cases":sum(c["delta"]==0 for c in changes),
            "weakest_cases":sorted(changes,key=lambda c:(c["adapter_token_f1"],c["delta"]))[:8],
            "regressions":sorted((c for c in changes if c["delta"]<0),key=lambda c:c["delta"]),
            "limitations":["Confidence interval describes this filtered public-data subset, not random-seed variability or real trade effectiveness",
                           "One training seed; fixed basic prompt; no optimized-prompt baseline yet",
                           "JSON validity is measured after the same decoding constraints in both models"]}


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--data",type=Path,required=True);p.add_argument("--experiment",type=Path,required=True)
    p.add_argument("--split",choices=["validation","test"],default="test");p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();result=analyze(a.data,a.experiment,a.split)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ["split","n","source_families","evidence_f1_gain","paired_source_family_bootstrap_95pct_ci","improved_cases","regressed_cases"]}))
