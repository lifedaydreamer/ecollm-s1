"""Validation-selected V2 trials, three seeds, then a previously unused-family confirmation set."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


def read(path): return json.loads(path.read_text())
def write(path, value): path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(); p.add_argument("--model", type=Path, required=True)
    p.add_argument("--data", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True); p.add_argument("--old-adapter", type=Path, required=True)
    p.add_argument("--baseline-suite", type=Path, help="Reuse only identity-checked completed V1 baselines from a driver-interrupted attempt")
    a = p.parse_args(); root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from tradepilot.artifacts import verify_clause_adapter
    verify_clause_adapter(a.old_adapter)
    if a.output.exists() and any(a.output.iterdir()): raise ValueError("Suite output must be new")
    a.output.mkdir(parents=True, exist_ok=True)
    def state(phase, **values):
        record = {"at": datetime.now(timezone.utc).isoformat(), "phase": phase, **values}
        write(a.output / "suite-state.json", record); print(json.dumps(record), flush=True)
    def run(script, *arguments):
        subprocess.run([sys.executable, str(root / "ml" / script), *map(str, arguments)], check=True, cwd=root)
    def evaluate_plan(plan, split, directory):
        path = a.output / (directory + "-plan.json"); write(path, plan)
        run("evaluate_clause_models.py", "--model", a.model, "--data", a.data / (split + ".jsonl"),
            "--plan", path, "--output", a.output / directory)
    config = read(a.config)
    write(a.output / "preregistered-plan.json", {
        "data_manifest_sha256": hashlib.sha256((a.data / "manifest.json").read_bytes()).hexdigest(),
        "candidate_a": config, "candidate_b_if_a_fails": {**config, "rank": 16, "alpha": 32, "learning_rate": 1e-4, "epochs": 1},
        "seeds": [42, 43, 44], "selection": "validation evidence F1 exceeds every V1/basic/guided and base/guided baseline by >= 2 percentage points; no >2 point response-grounding regression",
        "confirmation": "only after selection; all seeds reported; old test used solely for regression",
        "no_test_driven_selection": True})
    state("v1_validation_baselines")
    if a.baseline_suite:
        from tradepilot.clause_task import score
        previous_plan = read(a.baseline_suite / "preregistered-plan.json")
        if previous_plan["data_manifest_sha256"] != hashlib.sha256((a.data / "manifest.json").read_bytes()).hexdigest() or previous_plan["candidate_a"] != config:
            raise ValueError("Previous baselines used different frozen data or candidate configuration")
        rows = [json.loads(line) for line in (a.data / "validation.jsonl").read_text().splitlines()]
        hashes = {}
        for name, guided in (("v1-basic-validation", False), ("v1-guided-validation", True)):
            metrics_path = a.baseline_suite / "old-validation" / (name + "-metrics.json")
            predictions_path = a.baseline_suite / "old-validation" / (name + "-predictions.json")
            metrics, predictions = read(metrics_path), read(predictions_path)
            if [r["id"] for r in rows] != [v["id"] for v in predictions] or metrics.get("batch_size") != 4 or metrics.get("with_definitions") is not guided:
                raise ValueError("Baseline prediction identities or decoding policy differ")
            recomputed = score(rows, predictions)
            if any(metrics[key] != value for key, value in recomputed.items()):
                raise ValueError("Baseline recorded scores do not match its predictions")
            for path in (metrics_path, predictions_path): hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        shutil.copytree(a.baseline_suite / "old-validation", a.output / "old-validation")
        write(a.output / "reused-baselines.json", {"previous_suite": str(a.baseline_suite), "files_sha256": hashes,
            "validation_only": True, "fresh_confirmation_still_sealed": True})
        state("reused_verified_v1_validation_baselines")
    else:
        evaluate_plan([{"name": "v1-basic-validation", "adapter": str(a.old_adapter), "with_definitions": False},
                       {"name": "v1-guided-validation", "adapter": str(a.old_adapter), "with_definitions": True}], "validation", "old-validation")
    old_metrics = [read(a.output / "old-validation" / (n + "-metrics.json")) for n in ("v1-basic-validation", "v1-guided-validation")]
    candidates = [("candidate-a", config), ("candidate-b", {**config, "rank": 16, "alpha": 32, "learning_rate": 1e-4, "epochs": 1})]
    selected = None; trials = []
    for name, cfg in candidates:
        state("training", candidate=name, seed=42)
        path = a.output / (name + ".json"); write(path, cfg)
        run("train_clause_pilot.py", "--model", a.model, "--data", a.data, "--output", a.output / name, "--config", path)
        baseline = read(a.output / name / "base-validation-metrics.json")
        tuned = read(a.output / name / "adapter-validation-metrics.json")
        strongest = max([baseline, *old_metrics], key=lambda x: x["mean_evidence_token_f1"])
        passed = (tuned["mean_evidence_token_f1"] >= strongest["mean_evidence_token_f1"] + .02
                  and tuned["all_quotes_grounded_rate"] >= strongest["all_quotes_grounded_rate"] - .02)
        trials.append({"name": name, "config": cfg, "validation": tuned, "strongest_baseline": strongest, "passed": passed})
        write(a.output / "validation-trials.json", trials)
        if passed:
            selected = (name, cfg); break
    if selected is None:
        state("no_validated_gain", message="Confirmation kept sealed; neither preregistered candidate passed")
        return
    name, cfg = selected
    seed_paths = {42: a.output / name}
    for seed in (43, 44):
        state("replication_training", candidate=name, seed=seed)
        path = a.output / f"seed-{seed}.json"; write(path, {**cfg, "seed": seed})
        seed_paths[seed] = a.output / f"seed-{seed}"
        run("train_clause_pilot.py", "--model", a.model, "--data", a.data, "--output", seed_paths[seed], "--config", path)
    best_seed = max(seed_paths, key=lambda seed: read(seed_paths[seed] / "adapter-validation-metrics.json")["mean_evidence_token_f1"])
    selection = {"selected_candidate": name, "best_validation_seed": best_seed,
                 "seed_paths": {str(k): str(v) for k, v in seed_paths.items()},
                 "selected_before_confirmation_at": datetime.now(timezone.utc).isoformat(),
                 "confirmation_sha256": hashlib.sha256((a.data / "test.jsonl").read_bytes()).hexdigest(),
                 "test_selection_forbidden": True}
    write(a.output / "selection.json", selection)
    plan = [{"name": "base-basic", "with_definitions": False}, {"name": "base-guided", "with_definitions": True},
            {"name": "v1-basic", "adapter": str(a.old_adapter), "with_definitions": False},
            {"name": "v1-guided", "adapter": str(a.old_adapter), "with_definitions": True}]
    plan += [{"name": f"v2-seed-{seed}", "adapter": str(path / "adapter"), "with_definitions": True} for seed, path in seed_paths.items()]
    state("new_family_confirmation", best_validation_seed=best_seed)
    evaluate_plan(plan, "test", "confirmation")
    state("old_test_regression")
    evaluate_plan([{"name": "v1-basic", "adapter": str(a.old_adapter), "with_definitions": False},
                   {"name": "v2-selected", "adapter": str(seed_paths[best_seed] / "adapter"), "with_definitions": True}],
                  "regression", "regression")
    state("complete", best_validation_seed=best_seed)


if __name__ == "__main__": main()
