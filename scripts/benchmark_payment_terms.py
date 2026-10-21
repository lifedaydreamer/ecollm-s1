"""Before/after controlled payment parsing coverage; not an independent accuracy benchmark."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tradepilot.engine import extract, extract_explicit, evidence_valid


def run(dataset):
    results = {}
    for name, parser in (("previous_literal_parser", extract_explicit), ("payment_phrase_parser", extract)):
        tp = fp = fn = passed = evidence_ok = count = 0; cases = []; started = time.perf_counter()
        for spec in dataset["cases"]:
            doc = {"id": "contract", "kind": "contract", "name": "contract.txt",
                   "blocks": [{"id": "b1", "text": spec["text"], "location": "line 1"}]}
            facts = [f for f in parser(doc) if f["field"] in spec["expected"]]
            actual = {(f["field"], f["value"]) for f in facts}
            expected = {(field, value) for field, values in spec["expected"].items() for value in values}
            tp += len(actual & expected); fp += len(actual - expected); fn += len(expected - actual)
            passed += actual == expected
            evidence_ok += sum(evidence_valid(f["evidence"], [doc]) for f in facts); count += len(facts)
            cases.append({"id": spec["id"], "passed": actual == expected,
                          "missing": sorted(expected - actual), "unexpected": sorted(actual - expected)})
        results[name] = {"cases": len(cases), "exact_cases": passed, "exact_case_rate": passed / len(cases),
                         "tp": tp, "fp": fp, "fn": fn, "field_micro_f1": 2 * tp / max(2 * tp + fp + fn, 1),
                         "emitted_fact_evidence_match": evidence_ok / count if count else None,
                         "elapsed_ms": (time.perf_counter() - started) * 1000, "details": cases}
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--output", type=Path, required=True); a = p.parse_args()
    root = Path(__file__).resolve().parents[1]; source = root / "data/benchmarks/payment-terms.json"
    report = {"kind": "controlled_engineering_coverage_not_independent_quality", "model_calls": 0,
              "dataset_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "limitation": "Self-authored cases created alongside the rules; does not establish general business accuracy",
              "results": run(json.loads(source.read_text()))}
    a.output.parent.mkdir(parents=True, exist_ok=True); a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({name: {k: v for k, v in values.items() if k != "details"} for name, values in report["results"].items()}))
    if report["results"]["payment_phrase_parser"]["exact_case_rate"] != 1:
        raise SystemExit("Controlled payment regression failed")
