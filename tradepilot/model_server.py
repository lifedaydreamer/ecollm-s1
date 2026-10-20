"""Standalone inference API for a local Qwen base or base + adapter."""
import json
import os
import secrets
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException
from .schema import AnalyzeRequest, AnalyzeResponse
from .model import SYSTEM_PROMPT


def app_factory():
    model_path = os.environ["TRADEPILOT_MODEL_PATH"]
    token = os.environ["TRADEPILOT_MODEL_TOKEN"]
    adapter = os.getenv("TRADEPILOT_ADAPTER_PATH")
    if adapter:
        from .artifacts import reject_clause_adapter_for_business
        reject_clause_adapter_for_business(adapter)
    lock = threading.Lock()
    state = {}

    @asynccontextmanager
    async def lifespan(app):
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        if not os.getenv("CUDA_VISIBLE_DEVICES", "").startswith("GPU-"):
            raise RuntimeError("必须通过 gpu_guard.py 绑定单张 GPU UUID")
        fraction = float(os.getenv("TRADEPILOT_MODEL_MEMORY_FRACTION", "0.35"))
        if not 0 < fraction <= 0.9:
            raise RuntimeError("Model memory fraction must be between 0 and 0.9")
        torch.cuda.set_per_process_memory_fraction(fraction, 0)
        torch.set_num_threads(2)
        torch.manual_seed(42)
        state["tokenizer"] = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
        model = AutoModelForCausalLM.from_pretrained(model_path, dtype=torch.bfloat16,
                    local_files_only=True, trust_remote_code=False).to("cuda:0").eval()
        if adapter:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter, local_files_only=True).eval()
        state["model"] = model
        yield
        del state["model"]
        torch.cuda.empty_cache()

    app = FastAPI(title="TradePilot-LM", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok", "ready": "model" in state, "adapter_loaded": bool(os.getenv("TRADEPILOT_ADAPTER_PATH"))}

    @app.post("/v1/analyze", response_model=AnalyzeResponse)
    def analyze(body: AnalyzeRequest, x_api_key: str = Header(default="")):
        if not secrets.compare_digest(x_api_key, token):
            raise HTTPException(401, "Invalid model credential")
        import torch
        tokenizer = state["tokenizer"]
        schema = AnalyzeResponse.model_json_schema()
        # Free-form dictionaries are never generated: knowledge citations are added by the server.
        # Also keep each task bounded so extraction cannot drift into a long unsolicited report.
        schema["$defs"]["Finding"]["properties"].pop("basis", None)
        for model in ("Fact", "Finding"):
            schema["$defs"][model]["properties"].pop("id", None)
        schema["$defs"]["Fact"]["properties"].pop("confirmed", None)
        schema["properties"]["facts"]["maxItems"] = 20 if body.task == "extract" else 0
        schema["properties"]["findings"]["maxItems"] = 0 if body.task == "extract" else 4
        schema["properties"]["limitations"]["maxItems"] = 3
        for field, limit in [("title", 80), ("explanation", 200), ("suggestion", 160), ("key", 100)]:
            schema["$defs"]["Finding"]["properties"][field]["maxLength"] = limit
        schema["$defs"]["Finding"]["properties"]["evidence"]["minItems"] = 1
        schema["$defs"]["Finding"]["properties"]["evidence"]["maxItems"] = 4
        messages = [{"role": "system", "content": SYSTEM_PROMPT + "\nOnly perform the requested task. Raw and value are strings. Do not generate IDs, confirmed flags, or external citations.\nJSON Schema:\n" + json.dumps(schema)},
                    {"role": "user", "content": body.model_dump_json()}]
        encoded = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=True, return_tensors="pt").to("cuda:0")
        if encoded.shape[1] > 10000:
            raise HTTPException(413, "Context too long; split at clause boundaries, do not truncate evidence")
        if not lock.acquire(blocking=False):
            raise HTTPException(429, "Single-request inference limit; retry later")
        try:
            from lmformatenforcer import JsonSchemaParser
            from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn
            prefix = build_transformers_prefix_allowed_tokens_fn(tokenizer, JsonSchemaParser(schema))
            with torch.inference_mode():
                output = state["model"].generate(encoded, attention_mask=torch.ones_like(encoded), max_new_tokens=3072 if body.task == "extract" else 1800, max_time=90, do_sample=False,
                              pad_token_id=tokenizer.eos_token_id, prefix_allowed_tokens_fn=prefix)
            text = tokenizer.decode(output[0, encoded.shape[1]:], skip_special_tokens=True).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            try:
                result = AnalyzeResponse.model_validate_json(text)
                if body.task == "extract":
                    result.findings = []
                else:
                    result.facts = []
                    if len(result.findings) >= 4:
                        result.limitations.append("语义单次优先返回四项，请人工复核其余条款。")
                return result
            except ValueError as exc:
                if os.getenv("TRADEPILOT_DEBUG_MODEL") == "1":
                    from pathlib import Path
                    path = Path(".data/model-debug")
                    path.mkdir(parents=True, exist_ok=True)
                    (path / (body.task + ".txt")).write_text(text)
                details = [{"type":e["type"],"loc":e["loc"]} for e in exc.errors()[:4]] if hasattr(exc,"errors") else []
                raise HTTPException(502, {"message":"Model output failed schema validation", "errors":details}) from exc
        finally:
            lock.release()

    return app
