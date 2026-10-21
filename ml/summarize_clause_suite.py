"""Audit the sealed-family confirmation and report paired uncertainty and seed variability."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tradepilot.clause_task import score


def summarize(data, suite):
    selection = json.loads((suite / "selection.json").read_text())
    raw = (data / "test.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == selection["confirmation_sha256"]
    rows = [json.loads(line) for line in raw.decode().splitlines()]
    names = ["base-basic", "base-guided", "v1-basic", "v1-guided", "v2-seed-42", "v2-seed-43", "v2-seed-44"]
    predictions = {}; metrics = {}; individual = {}
    for name in names:
        values = json.loads((suite / "confirmation" / (name + "-predictions.json")).read_text())
        mapping = {v["id"]: v for v in values}
        if len(mapping) != len(rows) or set(mapping) != {r["id"] for r in rows}:
            raise ValueError("Prediction identity mismatch")
        values = [mapping[r["id"]] for r in rows]; predictions[name] = values
        metrics[name] = score(rows, values)
        recorded = json.loads((suite / "confirmation" / (name + "-metrics.json")).read_text())
        assert metrics[name]["mean_evidence_token_f1"] == recorded["mean_evidence_token_f1"]
        metrics[name]["elapsed_seconds"] = recorded["elapsed_seconds"]
        quotes = [q for r, p in zip(rows, values) for q in p.get("output", {}).get("evidence", [])]
        matched = sum(q in r["input"]["text"] for r, p in zip(rows, values) for q in p.get("output", {}).get("evidence", []))
        metrics[name]["emitted_quote_grounding"] = {"matched": matched, "emitted": len(quotes),
            "rate": matched / len(quotes) if quotes else None}
        individual[name] = [score([r], [p])["mean_evidence_token_f1"] for r, p in zip(rows, values)]
    individual["v2-seed-mean"] = [statistics.mean(individual[f"v2-seed-{s}"][i] for s in (42, 43, 44)) for i in range(len(rows))]
    selected = f"v2-seed-{selection['best_validation_seed']}"
    comparisons = {}
    for improved, baseline in [(selected, "v1-basic"), (selected, "v1-guided"), (selected, "base-guided"),
                               ("v2-seed-mean", "v1-basic"), ("v2-seed-mean", "v1-guided")]:
        changes = [a - b for a, b in zip(individual[improved], individual[baseline])]
        grouped = defaultdict(list)
        for row, change in zip(rows, changes): grouped[row["source"]["family"]].append(change)
        families = sorted(grouped); generator = random.Random(20261020); estimates = []
        for _ in range(2000):
            sampled = [v for _ in families for v in grouped[generator.choice(families)]]
            estimates.append(statistics.mean(sampled))
        estimates.sort()
        comparisons[improved + "_vs_" + baseline] = {"mean_gain": statistics.mean(changes),
            "paired_family_bootstrap_95pct_ci": [estimates[49], estimates[1949]],
            "improved": sum(v > 0 for v in changes), "regressed": sum(v < 0 for v in changes), "unchanged": sum(v == 0 for v in changes)}
    seeds = {}
    for metric in ("mean_evidence_token_f1", "clause_presence_macro_f1", "exact_span_set_match_rate"):
        values = [metrics[f"v2-seed-{s}"][metric] for s in (42, 43, 44)]
        seeds[metric] = {"values": values, "mean": statistics.mean(values), "sample_std": statistics.stdev(values)}
    before, after = predictions["v1-basic"], predictions[selected]
    cases = []
    for i, row in enumerate(rows):
        cases.append({"id": row["id"], "category": row["input"]["category"],
                      "gain": individual[selected][i] - individual["v1-basic"][i],
                      "before": before[i].get("output"), "after": after[i].get("output"),
                      "expected": row["target"], "text": row["input"]["text"]})
    return {"n": len(rows), "families": len({r["source"]["family"] for r in rows}),
            "selected_by_validation": selected, "confirmation_sha256": hashlib.sha256(raw).hexdigest(),
            "metrics": metrics, "comparisons": comparisons, "seed_variability": seeds,
            "improvement_examples": sorted(cases, key=lambda c: c["gain"], reverse=True)[:4],
            "regression_examples": sorted(cases, key=lambda c: c["gain"])[:4],
            "limitations": ["Filtered public contract excerpt tasks; not trade-risk accuracy or Agent completion",
                            "Single configuration selected on the original validation set; three training seeds",
                            "Family bootstrap measures confirmation-source variability; seed standard deviation reported separately",
                            "Issuer aliases, near duplicates, annotation noise and pretraining contamination are not completely excluded"]}


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--data", type=Path, required=True); p.add_argument("--suite", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True); a = p.parse_args()
    result = summarize(a.data, a.suite); a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"selected": result["selected_by_validation"], "seed_variability": result["seed_variability"], "comparisons": result["comparisons"]}))
