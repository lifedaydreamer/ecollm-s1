"""Preserve CUAD expert spans; do not turn clause types into invented risk labels."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tradepilot.clause_task import CATEGORIES

SOURCE_BLOB = "1ae94ff0a9b70b2e3b9b8d215737c8bfae460ddc"
SOURCE_COMMIT = "67faa0e6023b04fcaae6cc09497ab00e5d63a2a2"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def family(title):
    return re.sub(r"[^a-z0-9]", "", title.split("_")[0].lower())


def prepare(archive, output):
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Refuse to overwrite a frozen dataset; choose a new output directory")
    raw = archive.read_bytes()
    if hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest() != SOURCE_BLOB:
        raise ValueError("CUAD source blob changed; inspect a new version before use")
    with ZipFile(archive) as z:
        documents = json.loads(z.read("CUADv1.json"))["data"]
        test_titles = {d["title"] for d in json.loads(z.read("test.json"))["data"]}
    test_families = {family(t) for t in test_titles}
    candidates = {s:[] for s in ("train","validation","test")}
    audit = Counter()
    family_sets = {s:set() for s in candidates}
    for doc in documents:
        title = doc["title"]
        issuer = family(title)
        if title in test_titles:
            split = "test"
        elif issuer in test_families:
            audit["train_contracts_removed_due_to_test_issuer"] += 1
            continue
        else:
            split = "validation" if int(digest(issuer)[:8],16)%5 == 0 else "train"
        family_sets[split].add(issuer)
        for paragraph_index, para in enumerate(doc["paragraphs"]):
            text = para["context"]
            annotations = {q["id"].rsplit("__",1)[-1]:q for q in para["qas"]}
            for category in CATEGORIES:
                qa = annotations.get(category)
                if qa is None:
                    continue
                answers = []
                malformed = False
                for answer in qa["answers"]:
                    start, quote = answer["answer_start"], answer["text"]
                    if not quote.strip() or text[start:start+len(quote)] != quote:
                        audit["invalid_source_offsets"] += 1
                        malformed = True
                        break
                    answers.append((start,start+len(quote),quote))
                if malformed:
                    continue
                # Fixed windows are independent of gold answer positions.
                for start in range(0,len(text),1200):
                    end = min(start+1600,len(text))
                    if end-start < 120:
                        continue
                    intersect = [(a,b,q) for a,b,q in answers if a < end and b > start]
                    if any(a < start or b > end for a,b,_ in intersect):
                        audit["partial_gold_windows_removed"] += 1
                        continue
                    quotes = sorted({q for a,b,q in intersect})
                    if len(quotes)>8:
                        audit["too_many_spans_removed"] += 1
                        continue
                    excerpt = text[start:end]
                    item = {"id":digest(title+f":{paragraph_index}:{start}:"+category)[:24],"split":split,
                            "input":{"category":category,"text":excerpt},
                            "target":{"status":"found" if quotes else "not_found_in_excerpt","evidence":quotes},
                            "source":{"dataset":"CUAD v1","title":title,"family":issuer,"start":start,"end":end,
                                      "annotation_id":qa["id"],"license":"CC-BY-4.0","annotation_origin":"upstream_expert_spans_preserved"},
                            "context_hash":digest(" ".join(re.findall(r"\w+",excerpt.lower())))}
                    candidates[split].append(item)
    # Keep official test contracts, but remove exact normalized context overlap from lower-priority groups.
    test_hashes = {r["context_hash"] for r in candidates["test"]}
    validation_hashes = {r["context_hash"] for r in candidates["validation"]}
    limits = {"train":(60,20),"validation":(4,2),"test":(5,3)}
    selected = {}
    for split, (positive,negative) in limits.items():
        forbidden = test_hashes | validation_hashes if split == "train" else test_hashes if split == "validation" else set()
        seen = set()
        rows = []
        for category in CATEGORIES:
            for found, cap in [(True,positive),(False,negative)]:
                pool = sorted((r for r in candidates[split] if r["input"]["category"]==category and bool(r["target"]["evidence"])==found),key=lambda r:digest(r["id"]+":seed42"))
                count = 0
                for r in pool:
                    key = (category,r["context_hash"])
                    if r["context_hash"] in forbidden or key in seen:
                        continue
                    seen.add(key);rows.append(r);count+=1
                    if count>=cap:break
        selected[split] = rows
    output.mkdir(parents=True,exist_ok=True)
    for split,rows in selected.items():
        (output/(split+".jsonl")).write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in rows)+("\n" if rows else ""))
    assert not (family_sets["train"] & family_sets["validation"] or family_sets["train"] & family_sets["test"] or family_sets["validation"] & family_sets["test"])
    manifest = {"experiment":"cuad-clause-extraction-pilot-v1","status":"public_annotation_pilot_not_trade_risk_gold",
                "source":{"url":f"https://raw.githubusercontent.com/The-Atticus-Project/cuad/{SOURCE_COMMIT}/data.zip",
                          "git_blob_sha":SOURCE_BLOB,"sha256":hashlib.sha256(raw).hexdigest(),"license":"CC-BY-4.0",
                          "attribution":"The Atticus Project; Hendrycks, Burns, Chen and Ball (NeurIPS 2021)",
                          "paper":"https://arxiv.org/abs/2103.06268"},
                "categories":list(CATEGORIES),"counts":{s:len(r) for s,r in selected.items()},
                "distribution":{s:dict(Counter(r["input"]["category"]+":"+r["target"]["status"] for r in rows)) for s,rows in selected.items()},
                "families":{s:sorted({r["source"]["family"] for r in rows}) for s,rows in selected.items()},
                "files_sha256":{s:hashlib.sha256((output/(s+".jsonl")).read_bytes()).hexdigest() for s in selected},
                "audit":dict(audit),"window_chars":1600,"stride_chars":1200,
                "limitations":["Issuer-prefix families and exact normalized contexts are isolated; near-duplicate/template contamination is not fully excluded",
                               "CUAD pretraining contamination cannot be excluded","Commercial contracts, not exclusively cross-border goods trade",
                               "Labels preserve upstream clause spans; no human trade-risk labels or legal judgments were added",
                               "Windows intersecting partial gold spans are removed; results are conditional on this filtered subset"]}
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"counts":manifest["counts"],"audit":manifest["audit"],"output":str(output)},ensure_ascii=False))
    return manifest


if __name__ == "__main__":
    p=argparse.ArgumentParser();p.add_argument("--archive",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();prepare(a.archive,a.output)
