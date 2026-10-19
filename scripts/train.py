import argparse
import json
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument("--gpu",required=True);p.add_argument("--config",default="configs/train.yaml");a=p.parse_args()
    manifest=ROOT/"data/released/release-manifest.json"
    if not manifest.exists():
        raise SystemExit("拒绝训练：缺少经人工审核的数据发布清单。先执行 build_data.py --release。")
    m=json.loads(manifest.read_text())
    if not m.get("approved") or m.get("train_count",0)<3000:
        raise SystemExit("拒绝正式训练：需至少 3000 条审核后的训练任务。")
    for split, count in [("train",3000),("validation",500),("test",800)]:
        path=manifest.parent/f"{split}.jsonl"
        if m.get("counts",{}).get(split,0)<count or not path.exists():
            raise SystemExit("拒绝正式训练：独立数据分组未达到发布门槛。")
        if hashlib.sha256(path.read_bytes()).hexdigest()!=m.get("files_sha256",{}).get(split):
            raise SystemExit("拒绝正式训练：发布后数据发生变化，需重新审核发布。")
    return subprocess.call([sys.executable,str(ROOT/"scripts/gpu_guard.py"),"--gpu",a.gpu,"--min-free-mib","24000","--","llamafactory-cli","train",a.config],cwd=ROOT)

if __name__=="__main__":
    sys.exit(main())
