"""Evaluate an immutable named model plan only after validation-based selection."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    p = argparse.ArgumentParser(); p.add_argument("--model", required=True); p.add_argument("--data", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if not os.getenv("CUDA_VISIBLE_DEVICES", "").startswith("GPU-"):
        raise SystemExit("Launch under the exact GPU UUID resource guard")
    from tradepilot.artifacts import verify_base
    verify_base(a.model)
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    from ml.clause_evaluation import evaluate
    torch.set_num_threads(2); torch.manual_seed(42)
    cap = float(os.getenv("TRADEPILOT_MAX_ALLOCATOR_GIB", "22")) * 1024**3
    torch.cuda.set_per_process_memory_fraction(min(.7, cap / torch.cuda.get_device_properties(0).total_memory), 0)
    rows = [json.loads(line) for line in a.data.read_text().splitlines()]
    plan = json.loads(a.plan.read_text())
    a.output.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(a.model, local_files_only=True, trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.bfloat16, local_files_only=True,
                                               trust_remote_code=False, attn_implementation="sdpa").to("cuda:0")
    for item in plan:
        if (a.output / (item["name"] + "-metrics.json")).exists():
            raise ValueError("Refuse to overwrite an evaluated model")
        if item.get("adapter"):
            model = PeftModel.from_pretrained(model, item["adapter"], local_files_only=True)
        evaluate(model, tokenizer, rows, a.output, item["name"], batch_size=4,
                 with_definitions=item.get("with_definitions", True))
        if item.get("adapter"):
            model = model.unload()
        torch.cuda.empty_cache()


if __name__ == "__main__": main()
