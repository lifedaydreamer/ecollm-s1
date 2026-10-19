import argparse
import json
import os
from pathlib import Path
from .model import analyze_remote
from .schema import AnalyzeRequest


def main():
    p=argparse.ArgumentParser(description="TradePilot independent model client")
    p.add_argument("input",type=Path,help="JSON AnalyzeRequest file")
    p.add_argument("--endpoint",default=os.getenv("TRADEPILOT_MODEL_URL"))
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    if not a.endpoint: p.error("必须指定 --endpoint，不能将规则输出伪装成模型结果")
    result=analyze_remote(AnalyzeRequest.model_validate_json(a.input.read_text()),a.endpoint)
    text=result.model_dump_json(indent=2)
    if a.output:a.output.write_text(text)
    else:print(text)
