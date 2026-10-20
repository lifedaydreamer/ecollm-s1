"""Independent inference entry for a base model or the pilot clause adapter."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tradepilot.clause_task import messages, parse_prediction, OUTPUT_SCHEMA
from tradepilot.artifacts import verify_base, verify_clause_adapter


def main():
    p=argparse.ArgumentParser();p.add_argument("--model",required=True);p.add_argument("--adapter");p.add_argument("--input",type=Path,required=True)
    a=p.parse_args()
    if not os.getenv("CUDA_VISIBLE_DEVICES","").startswith("GPU-"):
        raise SystemExit("Launch through scripts/gpu_guard.py with an explicitly allocated GPU UUID")
    body=json.loads(a.input.read_text())
    prompt=messages({"input":body})
    verify_base(a.model)
    if a.adapter:
        verify_clause_adapter(a.adapter)
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM
    from lmformatenforcer import JsonSchemaParser
    from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn
    torch.set_num_threads(2);torch.manual_seed(42);torch.cuda.set_per_process_memory_fraction(0.7,0)
    tokenizer=AutoTokenizer.from_pretrained(a.model,local_files_only=True,trust_remote_code=False)
    ids=tokenizer.apply_chat_template(prompt,tokenize=True,add_generation_prompt=True,enable_thinking=False,return_tensors="pt")
    if ids.shape[1]+768>2048:
        raise SystemExit("Excerpt too long for this pilot; split it without dropping evidence")
    model=AutoModelForCausalLM.from_pretrained(a.model,dtype=torch.bfloat16,local_files_only=True,trust_remote_code=False).to("cuda:0")
    if a.adapter:
        from peft import PeftModel
        model=PeftModel.from_pretrained(model,a.adapter,local_files_only=True)
    model.eval();ids=ids.to("cuda:0")
    prefix=build_transformers_prefix_allowed_tokens_fn(tokenizer,JsonSchemaParser(OUTPUT_SCHEMA))
    with torch.inference_mode():
        result=model.generate(ids,attention_mask=torch.ones_like(ids),max_new_tokens=768,do_sample=False,pad_token_id=tokenizer.eos_token_id,prefix_allowed_tokens_fn=prefix)
    output,grounded=parse_prediction(tokenizer.decode(result[0,ids.shape[1]:],skip_special_tokens=True).strip(),body["text"])
    print(json.dumps({"result":output,"quotes_verified":grounded,"scope":"clause extraction, not trade-risk judgment"},ensure_ascii=False))


if __name__=="__main__":main()
