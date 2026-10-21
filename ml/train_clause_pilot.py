"""Small, auditable LoRA experiment. Launch ONLY through scripts/gpu_guard.py."""
import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tradepilot.clause_task import messages, parse_prediction, score, OUTPUT_SCHEMA


def write(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--model",type=Path,required=True);p.add_argument("--data",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True);p.add_argument("--config",type=Path,required=True)
    p.add_argument("--prepare-only",action="store_true")
    args=p.parse_args()
    config=json.loads(args.config.read_text());manifest=json.loads((args.data/"manifest.json").read_text())
    if manifest.get("status")!="public_annotation_pilot_not_trade_risk_gold":
        raise SystemExit("This launcher only accepts the separately documented public-annotation pilot")
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit("Refuse to overwrite an existing experiment")
    rows={}
    for split in ("train","validation","test"):
        source=(args.data/(split+".jsonl")).read_bytes()
        if hashlib.sha256(source).hexdigest()!=manifest["files_sha256"][split]:
            raise SystemExit("Dataset changed after its manifest was frozen")
        rows[split]=[json.loads(line) for line in source.decode().splitlines() if line]
    if not rows["train"] or not rows["validation"] or not rows["test"]:
        raise SystemExit("All independent partitions must be nonempty")
    families={s:{r["source"]["family"] for r in rs} for s,rs in rows.items()}
    contexts={s:{r["context_hash"] for r in rs} for s,rs in rows.items()}
    for a,b in (("train","validation"),("train","test"),("validation","test")):
        if families[a]&families[b] or contexts[a]&contexts[b]:
            raise SystemExit("Source or exact context leakage")
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(str(args.model),local_files_only=True,trust_remote_code=False)
    training=[]
    lengths=[]
    for row in rows["train"]:
        prompt=messages(row, with_definitions=config.get("with_definitions", False))
        prefix=tokenizer.apply_chat_template(prompt,tokenize=True,add_generation_prompt=True,enable_thinking=False)
        full=tokenizer.apply_chat_template(prompt+[{"role":"assistant","content":json.dumps(row["target"],ensure_ascii=False)}],tokenize=True,add_generation_prompt=False,enable_thinking=False)
        if full[:len(prefix)]!=prefix:
            raise SystemExit("Assistant token boundary mismatch; never train on prompt tokens")
        if len(full)>config["cutoff_len"]:
            raise SystemExit("Evidence would be truncated; change the data release, not silent token truncation")
        lengths.append(len(full))
        training.append({"input_ids":full,"attention_mask":[1]*len(full),"labels":[-100]*len(prefix)+full[len(prefix):]})
    for split in ("validation","test"):
        for row in rows[split]:
            n=len(tokenizer.apply_chat_template(messages(row, with_definitions=config.get("with_definitions", False)),tokenize=True,add_generation_prompt=True,enable_thinking=False))
            if n+config["max_new_tokens"]>config["cutoff_len"]:
                raise SystemExit("Evaluation context exceeds the frozen token budget")
    metadata={"config":config,"config_sha256":hashlib.sha256(args.config.read_bytes()).hexdigest(),
              "data_manifest_sha256":hashlib.sha256((args.data/"manifest.json").read_bytes()).hexdigest(),
              "model_dir":str(args.model),"max_train_tokens":max(lengths),"counts":{s:len(rs) for s,rs in rows.items()},
              "scope":"public-annotation pilot; not a professional trade-risk model", "test_policy":"test evaluated only if validation gain gate passes"}
    base_manifest=json.loads((Path(__file__).resolve().parents[1]/"configs/model-manifest.json").read_text())
    print("Verifying local base model identity without loading GPU weights",flush=True)
    identity={}
    for name,expected in base_manifest["sha256"].items():
        with (args.model/name).open("rb") as file:
            value=hashlib.file_digest(file,"sha256").hexdigest()
        if value != expected:
            raise SystemExit("Base model hash mismatch: "+name)
        identity[name]=value
    metadata["model_files_sha256"]=identity
    source_root=Path(__file__).resolve().parents[1]
    metadata["source_sha256"]={name:hashlib.sha256((source_root/name).read_bytes()).hexdigest() for name in
                              ["ml/train_clause_pilot.py","ml/prepare_cuad.py","tradepilot/clause_task.py"]}
    if config.get("with_definitions") or config.get("eval_batch_size", 1) > 1:
        for name in ["ml/clause_evaluation.py", "configs/cuad-category-definitions.json"]:
            metadata["source_sha256"][name] = hashlib.sha256((source_root/name).read_bytes()).hexdigest()
    print(json.dumps({"preflight":"passed","max_train_tokens":max(lengths),"counts":metadata["counts"]}),flush=True)
    if args.prepare_only:
        return
    if not os.getenv("CUDA_VISIBLE_DEVICES","").startswith("GPU-"):
        raise SystemExit("Use the resource guard with an exact GPU UUID")
    import torch
    import peft
    import transformers
    from peft import LoraConfig,get_peft_model
    from transformers import AutoModelForCausalLM,Trainer,TrainingArguments,DataCollatorForSeq2Seq,TrainerCallback
    from lmformatenforcer import JsonSchemaParser
    from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn
    torch.set_num_threads(2);torch.manual_seed(config["seed"]);random.seed(config["seed"])
    cap = float(os.getenv("TRADEPILOT_MAX_ALLOCATOR_GIB", config.get("memory_limit_gib", 1e9))) * 1024**3
    fraction = min(config["memory_fraction"], cap / torch.cuda.get_device_properties(0).total_memory)
    torch.cuda.set_per_process_memory_fraction(fraction,0)
    args.output.mkdir(parents=True,exist_ok=True)
    metadata["versions"]={"torch":torch.__version__,"transformers":transformers.__version__,"peft":peft.__version__}
    metadata["effective_allocator_limit_gib"] = fraction * torch.cuda.get_device_properties(0).total_memory / 1024**3
    metadata["gpu_uuid"]=os.environ["CUDA_VISIBLE_DEVICES"]
    write(args.output/"experiment.json",metadata)
    model=AutoModelForCausalLM.from_pretrained(str(args.model),dtype=torch.bfloat16,local_files_only=True,trust_remote_code=False,attn_implementation="sdpa").to("cuda:0")

    def evaluate(name, dataset, disable_adapter=False):
        if config.get("eval_batch_size", 1) > 1 or config.get("with_definitions"):
            from ml.clause_evaluation import evaluate as batched_evaluate
            return batched_evaluate(model, tokenizer, dataset, args.output, name,
                batch_size=config.get("eval_batch_size", 1), with_definitions=config.get("with_definitions", False),
                max_new_tokens=config["max_new_tokens"], disable_adapter=disable_adapter)
        predictions=[];model.eval()
        active=model.disable_adapter() if disable_adapter else nullcontext()
        started=time.monotonic()
        with active,torch.inference_mode():
            for index,row in enumerate(dataset):
                ids=tokenizer.apply_chat_template(messages(row),tokenize=True,add_generation_prompt=True,enable_thinking=False,return_tensors="pt").to("cuda:0")
                prefix_allowed=build_transformers_prefix_allowed_tokens_fn(tokenizer,JsonSchemaParser(OUTPUT_SCHEMA))
                output=model.generate(ids,attention_mask=torch.ones_like(ids),do_sample=False,max_new_tokens=config["max_new_tokens"],
                    pad_token_id=tokenizer.eos_token_id,prefix_allowed_tokens_fn=prefix_allowed,use_cache=True)
                raw=tokenizer.decode(output[0,ids.shape[1]:],skip_special_tokens=True).strip()
                pred={"id":row["id"],"raw":raw,"schema_valid":False,"grounded":False}
                try:
                    pred["output"],pred["grounded"]=parse_prediction(raw,row["input"]["text"])
                    pred["schema_valid"]=True
                except (ValueError,TypeError):
                    pass
                predictions.append(pred)
                if (index+1)%6==0: print(json.dumps({"phase":name,"completed":index+1,"total":len(dataset)}),flush=True)
        result=score(dataset,predictions)
        result.update(elapsed_seconds=round(time.monotonic()-started,2),decoding="same JSON schema constraints; greedy",input_ids_sha256=hashlib.sha256(json.dumps([r["id"] for r in dataset]).encode()).hexdigest())
        write(args.output/(name+"-predictions.json"),predictions)
        write(args.output/(name+"-metrics.json"),result)
        print(json.dumps({"phase":name,"metrics":result}),flush=True)
        return result

    base=evaluate("base-validation",rows["validation"])
    model=get_peft_model(model,LoraConfig(r=config["rank"],lora_alpha=config["alpha"],lora_dropout=config["dropout"],
                                       target_modules=config["target_modules"],bias="none",task_type="CAUSAL_LM"))
    model.enable_input_require_grads();model.config.use_cache=False
    class Progress(TrainerCallback):
        def on_log(self,args,state,control,logs=None,**kwargs):
            import math
            if logs and "loss" in logs and not math.isfinite(logs["loss"]):
                raise RuntimeError("Non-finite training loss; experiment stopped")
            with (Path(args.output_dir)/"progress.jsonl").open("a") as file:
                file.write(json.dumps({"step":state.global_step,**(logs or {}),"gpu_peak_mib":torch.cuda.max_memory_allocated()/1024**2})+"\n")
    train_args=TrainingArguments(output_dir=str(args.output),per_device_train_batch_size=config["batch_size"],gradient_accumulation_steps=config["gradient_accumulation"],
        num_train_epochs=config["epochs"],learning_rate=config["learning_rate"],lr_scheduler_type="cosine",warmup_ratio=0.03,
        bf16=True,gradient_checkpointing=True,gradient_checkpointing_kwargs={"use_reentrant":False},logging_steps=10,save_strategy="no",eval_strategy="no",
        report_to="none",seed=config["seed"],data_seed=config["seed"],dataloader_num_workers=0,optim="adamw_torch",max_grad_norm=1,disable_tqdm=True,logging_nan_inf_filter=False)
    trainer=Trainer(model=model,args=train_args,train_dataset=training,data_collator=DataCollatorForSeq2Seq(tokenizer,padding=True,label_pad_token_id=-100),callbacks=[Progress()])
    started=time.monotonic();trained=trainer.train()
    model.save_pretrained(args.output/"adapter",safe_serialization=True)
    write(args.output/"training-metrics.json",{**trained.metrics,"elapsed_seconds":time.monotonic()-started,"gpu_peak_mib":torch.cuda.max_memory_allocated()/1024**2,
                                           "trainable_parameters":sum(p.numel() for p in model.parameters() if p.requires_grad)})
    model.gradient_checkpointing_disable();model.config.use_cache=True
    tuned=evaluate("adapter-validation",rows["validation"])
    gain=tuned["mean_evidence_token_f1"]-base["mean_evidence_token_f1"]
    accepted=(gain>=config["minimum_validation_gain"] and tuned["all_quotes_grounded_rate"]>=base["all_quotes_grounded_rate"]-0.02)
    summary={"validation_evidence_f1_gain":gain,"validation_gate_passed":accepted,"not_a_formal_model_release":True}
    if accepted and not config.get("defer_test", False):
        summary["base_test"]=evaluate("base-test",rows["test"],disable_adapter=True)
        summary["adapter_test"]=evaluate("adapter-test",rows["test"])
    else:
        summary["test_status"]="kept sealed; validation gate did not pass or suite defers confirmation until selection"
    summary["adapter_sha256"]={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.output/"adapter").iterdir() if p.is_file()}
    write(args.output/"summary.json",summary)
    print(json.dumps({"phase":"complete",**summary}),flush=True)


if __name__=="__main__":
    main()
