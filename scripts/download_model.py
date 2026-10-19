"""Download a pinned public base model remotely, with a bounded storage budget."""
import json
import argparse
import hashlib
from pathlib import Path
import shutil
from huggingface_hub import HfApi, snapshot_download

parser=argparse.ArgumentParser()
parser.add_argument("--source",choices=["huggingface","modelscope"],default="huggingface")
args=parser.parse_args()

path=Path("/data/yzh/tradepilot-models/Qwen3-4B-Instruct-2507")
path.parent.mkdir(parents=True,exist_ok=True)
if shutil.disk_usage(path.parent).free < 80*1024**3:
    raise SystemExit("拒绝下载：必须保留至少 80GiB 可用磁盘")
if args.source=="modelscope":
    from modelscope.hub.api import HubApi
    from modelscope import snapshot_download as ms_download
    repo="Qwen/Qwen3-4B-Instruct-2507"
    files=HubApi().get_model_files(repo,recursive=True)
    size=sum(f.get("Size",0) for f in files)
    if size>12*1024**3:raise SystemExit("模型超过下载预算")
    print(json.dumps({"source":"modelscope","repo":repo,"bytes":size}),flush=True)
    ms_download(repo,local_dir=str(path),allow_file_pattern=["*.json","*.safetensors","*.txt","*.model"],max_workers=2)
    hashes={str(f.relative_to(path)):hashlib.sha256(f.read_bytes()).hexdigest() for f in path.iterdir() if f.is_file() and f.suffix in {".safetensors",".json"}}
    (path/"tradepilot-provenance.json").write_text(json.dumps({"source":"official Qwen ModelScope publication","repo":repo,"files":files,"local_sha256":hashes},indent=2))
    print("DOWNLOAD_COMPLETE",path)
    raise SystemExit(0)
info=HfApi().model_info("Qwen/Qwen3-4B-Instruct-2507",files_metadata=True)
size=sum(s.size or 0 for s in info.siblings if s.rfilename.endswith((".safetensors",".json",".txt")))
if size>12*1024**3:
    raise SystemExit("模型文件超过 12GiB 下载预算")
print(json.dumps({"repo":info.id,"revision":info.sha,"bytes":size}),flush=True)
snapshot_download(info.id, revision=info.sha,local_dir=path,
    allow_patterns=["*.json","*.safetensors","*.txt","*.model"],max_workers=2)
(path/"tradepilot-provenance.json").write_text(json.dumps({"repo":info.id,"revision":info.sha,"estimated_bytes":size},indent=2))
print("DOWNLOAD_COMPLETE",path)
