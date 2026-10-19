"""One synthetic integration check against an already running model, never training."""
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tradepilot.model import analyze_remote
from tradepilot.schema import AnalyzeRequest


def main():
    if not os.environ.get("TRADEPILOT_MODEL_URL"):
        raise SystemExit("请先配置已有模型接口；此检查不下载或启动模型。")
    texts = [("quote", "The Buyer shall pay a deposit of 30% before shipment. The remaining 70% is payable within 30 days after receipt of the bill of lading copy."),
             ("contract", "No deposit is required. The Buyer shall pay the entire price within 90 days after delivery of the goods.")]
    documents = [{"id":kind,"kind":kind,"name":kind+".txt", "blocks":[{"id":"b1","text":text,"location":"line 1"}]} for kind,text in texts]
    started = time.monotonic()
    result = analyze_remote(AnalyzeRequest(task="compare", documents=documents))
    passed = result.comparison == "different" and any(f.kind == "difference" for f in result.findings)
    out = Path(".data/semantic-path-check.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"synthetic":True, "purpose":"single_integration_check_not_quality_evaluation", "passed":passed,
                              "elapsed_seconds":round(time.monotonic()-started,2), "request_documents":documents, "result":result.model_dump()},ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"passed":passed,"findings":len(result.findings),"comparison":result.comparison,
                      "limitations":result.limitations,"output":str(out)},ensure_ascii=False))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
