import hashlib
import json
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from .engine import review, extract
from .model import analyze_remote
from .schema import AnalyzeRequest, now


class State(TypedDict, total=False):
    documents: list[dict]
    reference_ids: list[str]
    policy: dict
    findings: list[dict]
    limitations: list[str]
    steps: list[dict]
    approved: bool
    knowledge_snapshot: str


def make_graph(checkpointer):
    def facts(state):
        docs = json.loads(json.dumps(state["documents"]))
        limitations = []
        for doc in docs:
            if not doc.get("facts"):
                doc["facts"] = extract(doc)
        if len(docs) > 8 or sum(len(b["text"]) for d in docs for b in d["blocks"]) > 40000:
            limitations.append("超过首版语义上下文限制，需分组审查；当前保留规则结果。")
        else:
            try:
                for current_doc in docs:
                    explicit_fields = {f["field"] for f in current_doc["facts"]}
                    if {"seller", "buyer", "currency", "total", "deposit_percent", "payment_days", "incoterm"}.issubset(explicit_fields):
                        continue
                    result = analyze_remote(AnalyzeRequest(task="extract", documents=[current_doc], policy=state["policy"]))
                    limitations.extend(result.limitations)
                    # Compare with the pre-extraction fields, not facts appended in this response.
                    # Otherwise a second, conflicting value is silently discarded.
                    for fact in result.facts:
                        doc = next(d for d in docs if d["id"] == fact.evidence.document_id)
                        if fact.field not in explicit_fields:
                            doc["facts"].append(fact.model_dump())
            except Exception as exc:
                limitations.append(f"语义抽取不可用（{type(exc).__name__}）；未静默替换模型结果。")
        return {"documents": docs, "limitations": limitations,
                "steps": [{"node": "extract", "at": now(), "status": "done"}]}

    def rules(state):
        return {"findings": review(state["documents"], state["reference_ids"], state["policy"]),
                "steps": state["steps"] + [{"node": "rules", "at": now(), "status": "done"}]}

    def semantic(state):
        findings, limitations = list(state["findings"]), list(state["limitations"])
        if len(state["documents"]) <= 8 and sum(len(b["text"]) for d in state["documents"] for b in d["blocks"]) <= 40000:
            try:
                contracts = [d for d in state["documents"] if d["kind"] == "contract"]
                if contracts:
                    target = contracts[-1]
                    requests = [AnalyzeRequest(task="review", documents=[target], policy=state["policy"])]
                    references = [d for d in state["documents"] if d["id"] in state["reference_ids"] and d["id"] != target["id"]]
                    requests += [AnalyzeRequest(task="compare", documents=[d,target], policy=state["policy"]) for d in references[:3]]
                    if len(references)>3:
                        limitations.append("语义比较每次最多处理三份参考材料，请拆分额外参考文件。")
                    for request in requests:
                        result = analyze_remote(request)
                        limitations += result.limitations
                        findings += [f.model_dump() for f in result.findings]
            except Exception as exc:
                limitations.append(f"语义审查不可用（{type(exc).__name__}），本次语义结果不完整。")
        unique = {f["key"]: f for f in findings}
        return {"findings": list(unique.values()), "limitations": list(dict.fromkeys(limitations)),
                "steps": state["steps"] + [{"node": "semantic", "at": now(), "status": "done"}]}

    def report(state):
        from pathlib import Path
        from .knowledge import KnowledgeStore, finding_topics
        path = Path(__file__).resolve().parents[1] / "data/knowledge.json"
        findings = json.loads(json.dumps(state["findings"]))
        if path.exists():
            store = KnowledgeStore(path)
            if state.get("knowledge_snapshot", store.snapshot) != store.snapshot:
                return {"limitations": state["limitations"] + ["知识库在运行中发生变化，请重新审查。"]}
            for finding in findings:
                finding["basis"] += store.search(finding["title"], topics=finding_topics(finding))
        return {"findings": findings, "steps": state["steps"] + [{"node": "report", "at": now(), "status": "done"}]}

    def approval(state):
        decision = interrupt({"action": "review_findings", "count": len(state["findings"])})
        return {"approved": decision.get("approved") is True,
                "steps": state["steps"] + [{"node": "approval", "at": now(), "status": "done"}]}

    graph = StateGraph(State)
    for name, fn in [("extract", facts), ("rules", rules), ("semantic", semantic), ("report", report), ("approval", approval)]:
        graph.add_node(name, fn)
    for a, b in [(START, "extract"), ("extract", "rules"), ("rules", "semantic"), ("semantic", "report"), ("report", "approval"), ("approval", END)]:
        graph.add_edge(a, b)
    return graph.compile(checkpointer=checkpointer)
