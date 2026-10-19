"""Generate draft teaching candidates, not expert gold or independent benchmarks."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tradepilot.demos import demo_documents
from tradepilot.engine import extract, review
from tradepilot.parsers import parse_document
from tradepilot.schema import Policy


def generate(output: Path, count=20):
    output.mkdir(parents=True,exist_ok=True)
    records=[]
    for i in range(count):
        variant=["normal","conflict","missing"][i%3]
        docs=[]
        for k,name,text in demo_documents(variant,i):
            blocks,warnings=parse_document(name,text.encode())
            doc={"id":f"case-{i}-{k}","kind":k,"name":name,"blocks":blocks,"warnings":warnings}
            doc["facts"]=extract(doc);docs.append(doc)
        policy=Policy().model_dump()
        records.append({"id":f"draft-{i}","source_family":"tradepilot-template-v1", "split":"train",
            "license":"CC0-1.0","synthetic":True,"review_status":"pending",
            "input":{"task":"review","documents":docs,"policy":policy},
            "candidate_output":{"facts":[],"findings":review(docs,[docs[1]["id"]],policy),"comparison":"different" if variant=="conflict" else "insufficient" if variant=="missing" else "consistent","limitations":[]}})
    path=output/"candidates.jsonl"
    path.write_text("\n".join(json.dumps(x,ensure_ascii=False) for x in records)+"\n")
    (output/"manifest.json").write_text(json.dumps({"records":len(records),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
        "reviewed":0,"status":"draft","limitations":"Same template family: training candidates only; never use as independent test evidence."},indent=2))
    print(path)


def release(path: Path, out: Path):
    rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows or any(r.get("review_status")!="approved" or not r.get("reviewer") for r in rows):
        raise ValueError("每条样本必须经过具名人工审核，不能将候选标签自动视为金标准")
    families={}
    for row in rows:
        families.setdefault(row["source_family"],set()).add(row["split"])
        if len(families[row["source_family"]])>1:
            raise ValueError("同一来源家族跨分组，存在泄漏")
        if row["split"] in {"validation","test"} and (not row.get("second_reviewer") or row["second_reviewer"]==row["reviewer"]):
            raise ValueError("验证和测试样本需独立复核")
    out.mkdir(parents=True,exist_ok=True)
    for split in ["train","validation","test"]:
        selected=[r for r in rows if r["split"]==split]
        (out/f"{split}.jsonl").write_text("\n".join(json.dumps({"instruction":"Review the supplied evidence and return structured JSON.","input":json.dumps(r["input"],ensure_ascii=False),"output":json.dumps(r["candidate_output"],ensure_ascii=False)},ensure_ascii=False) for r in selected))
    (out/"dataset_info.json").write_text(json.dumps({"tradepilot_"+split:{"file_name":split+".jsonl","columns":{"prompt":"instruction","query":"input","response":"output"}} for split in ["train","validation","test"]},indent=2))
    (out/"release-manifest.json").write_text(json.dumps({"approved":True,"source_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"train_count":sum(r["split"]=="train" for r in rows),"counts":{split:sum(r["split"]==split for r in rows) for split in ["train","validation","test"]},"files_sha256":{split:hashlib.sha256((out/f"{split}.jsonl").read_bytes()).hexdigest() for split in ["train","validation","test"]},"families":{k:list(v) for k,v in families.items()}},indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=Path("data/generated"));p.add_argument("--count",type=int,default=20);p.add_argument("--release",type=Path)
    a=p.parse_args()
    if a.release: release(a.release,a.output)
    else: generate(a.output,a.count)
