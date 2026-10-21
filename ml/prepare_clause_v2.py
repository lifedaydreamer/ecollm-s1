"""Expand expert labels without reusing the pilot's source families as new confirmation data."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.prepare_cuad import build_candidates, digest, SOURCE_COMMIT
from tradepilot.clause_task import CATEGORIES

KEYWORDS = {
    "Cap On Liability": r"liab|damages|claim|limit",
    "Uncapped Liability": r"liab|damages|except|notwithstanding",
    "Liquidated Damages": r"damages|terminat|fee|penalt",
    "Warranty Duration": r"warrant|defect|period|days|months",
    "Insurance": r"insur|indemn|liab",
    "Audit Rights": r"audit|inspect|record|books",
    "Termination For Convenience": r"terminat|notice|cause",
    "Governing Law": r"law|court|jurisdiction",
    "Minimum Commitment": r"minimum|commit|purchase|order",
}


def select(pool, positive, negative, hard_negative=False):
    rows = []
    for category in CATEGORIES:
        category_rows = [r for r in pool if r["input"]["category"] == category]
        used = set()
        for found, cap in ((True, positive), (False, negative)):
            candidates = [r for r in category_rows if bool(r["target"]["evidence"]) == found]
            candidates.sort(key=lambda r: digest(r["id"] + ":v2-frozen"))
            if hard_negative and not found:
                hard = [r for r in candidates if re.search(KEYWORDS[category], r["input"]["text"], re.I)]
                candidates = hard[:cap // 2] + candidates
            count = 0
            for row in candidates:
                if row["context_hash"] in used:
                    continue
                rows.append(row); used.add(row["context_hash"]); count += 1
                if count >= cap:
                    break
    return rows


def prepare(archive, pilot, output):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output must be new; never rewrite a frozen experiment")
    manifest = json.loads((pilot / "manifest.json").read_text())
    original = {}
    for split in ("train", "validation", "test"):
        source = (pilot / (split + ".jsonl")).read_bytes()
        if hashlib.sha256(source).hexdigest() != manifest["files_sha256"][split]:
            raise ValueError("Pilot dataset was modified")
        original[split] = [json.loads(line) for line in source.decode().splitlines()]
    used_families = {r["source"]["family"] for rows in original.values() for r in rows}
    train_families = {r["source"]["family"] for r in original["train"]}
    candidates, audit, _, raw = build_candidates(archive)
    pool = [r for rows in candidates.values() for r in rows]
    existing_eval_hashes = {r["context_hash"] for split in ("validation", "test") for r in original[split]}
    training = [r for r in pool if r["source"]["family"] in train_families and r["context_hash"] not in existing_eval_hashes]
    # Confirmation families were absent from ALL pilot partitions, including validation.
    old_family_hashes = {r["context_hash"] for r in pool if r["source"]["family"] in used_families}
    unseen = [r for r in pool if r["source"]["family"] not in used_families and r["context_hash"] not in old_family_hashes]
    selected = {"train": select(training, 200, 80, hard_negative=True),
                "validation": original["validation"],
                "test": select(unseen, 8, 4), "regression": original["test"]}
    for split, rows in selected.items():
        for row in rows:
            row["split"] = split
    output.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for split, rows in selected.items():
        path = output / (split + ".jsonl")
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        hashes[split] = hashlib.sha256(path.read_bytes()).hexdigest()
    families = {s: {r["source"]["family"] for r in rows} for s, rows in selected.items()}
    contexts = {s: {r["context_hash"] for r in rows} for s, rows in selected.items()}
    for a, b in (("train", "validation"), ("train", "test"), ("validation", "test")):
        assert not families[a] & families[b] and not contexts[a] & contexts[b]
    assert not families["test"] & used_families
    report = {"experiment": "cuad-clause-v2-confirmation", "status": "public_annotation_pilot_not_trade_risk_gold",
              "source_commit": SOURCE_COMMIT, "source_archive_sha256": hashlib.sha256(raw).hexdigest(),
              "pilot_manifest_sha256": hashlib.sha256((pilot / "manifest.json").read_bytes()).hexdigest(),
              "files_sha256": hashes, "counts": {s: len(rows) for s, rows in selected.items()},
              "families": {s: sorted(values) for s, values in families.items()},
              "distribution": {s: dict(Counter(r["input"]["category"] + ":" + r["target"]["status"] for r in rows)) for s, rows in selected.items()},
              "old_test_use": "regression only; no configuration selection on its results",
              "confirmation_policy": "source families absent from every V1 partition; evaluation only after validation selection",
              "selection": "maximum 200 positives/80 negatives per train category, half-negative quota prioritizes category keywords; max 8 positives/4 negatives per confirmation category",
              "license": "CC-BY-4.0, The Atticus Project; original expert spans, no new risk labels",
              "limitations": ["Filtered 1600-character windows; not full CUAD or trade-risk benchmark",
                              "Issuer prefix and exact context isolation; near duplicates and pretraining contamination not fully excluded"],
              "source_audit": dict(audit)}
    (output / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"counts": report["counts"], "families": {s: len(v) for s, v in families.items()}, "distribution": report["distribution"]}))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--pilot", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); prepare(a.archive, a.pilot, a.output)
