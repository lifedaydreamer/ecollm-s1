"""Identical constrained batched decoding for every compared clause model."""
from contextlib import nullcontext
import hashlib
import json
import time
from tradepilot.clause_task import messages, parse_prediction, score, OUTPUT_SCHEMA


def evaluate(model, tokenizer, dataset, output_dir, name, *, batch_size=1, with_definitions=False,
             max_new_tokens=768, disable_adapter=False):
    import torch
    from lmformatenforcer import JsonSchemaParser
    from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn
    predictions = []; model.eval(); started = time.monotonic()
    tokenizer.padding_side = "left"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    prompts = [tokenizer.apply_chat_template(messages(r, with_definitions=with_definitions), tokenize=False,
               add_generation_prompt=True, enable_thinking=False) for r in dataset]
    active = model.disable_adapter() if disable_adapter else nullcontext()
    with active, torch.inference_mode():
        for start in range(0, len(dataset), batch_size):
            rows = dataset[start:start + batch_size]
            encoded = tokenizer(prompts[start:start + batch_size], padding=True, add_special_tokens=False,
                                return_tensors="pt").to("cuda:0")
            if encoded["input_ids"].shape[1] + max_new_tokens > 2048:
                raise ValueError("Evaluation context exceeds the frozen token budget; no truncation allowed")
            prefix = build_transformers_prefix_allowed_tokens_fn(tokenizer, JsonSchemaParser(OUTPUT_SCHEMA))
            generated = model.generate(**encoded, do_sample=False, max_new_tokens=max_new_tokens,
                pad_token_id=tokenizer.pad_token_id, prefix_allowed_tokens_fn=prefix, use_cache=True)
            for row, tokens in zip(rows, generated[:, encoded["input_ids"].shape[1]:]):
                raw = tokenizer.decode(tokens, skip_special_tokens=True).strip()
                item = {"id": row["id"], "raw": raw, "schema_valid": False, "grounded": False}
                try:
                    item["output"], item["grounded"] = parse_prediction(raw, row["input"]["text"])
                    item["schema_valid"] = True
                except (ValueError, TypeError):
                    pass
                predictions.append(item)
            print(json.dumps({"phase": name, "completed": len(predictions), "total": len(dataset)}), flush=True)
    metrics = score(dataset, predictions)
    metrics.update(elapsed_seconds=round(time.monotonic() - started, 2), batch_size=batch_size,
                   with_definitions=with_definitions, max_new_tokens=max_new_tokens,
                   decoding="same JSON schema constraints; greedy; left padding",
                   input_ids_sha256=hashlib.sha256(json.dumps([r["id"] for r in dataset]).encode()).hexdigest())
    for suffix, value in (("predictions", predictions), ("metrics", metrics)):
        (output_dir / f"{name}-{suffix}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"phase": name, "metrics": metrics}), flush=True)
    return metrics
