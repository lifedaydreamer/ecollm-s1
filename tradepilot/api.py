import json
import os
import secrets
import sqlite3
import threading
import hashlib
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from .db import database, initialize, CaseRow, RunRow, encode, case_dict, run_dict
from .schema import NewCase, DecisionInput, Correction, ApprovalInput, Policy, now, uid
from .parsers import parse_document
from .engine import extract, extract_items, normalize
from .revisions import compare_runs
from .workflow import make_graph
from .reports import export


def create_app(db_url=None, data_dir=None, token=None):
    data = Path(data_dir or os.getenv("TRADEPILOT_DATA", ".data"))
    data.mkdir(parents=True, exist_ok=True)
    api_token = token or os.environ.get("TRADEPILOT_TOKEN")
    if not api_token:
        raise RuntimeError("Set TRADEPILOT_TOKEN before starting the API")
    engine, Session = database(db_url or os.getenv("DATABASE_URL", f"sqlite:///{data}/app.sqlite"))
    initialize(engine)
    checkpoint_connection = sqlite3.connect(data / "checkpoints.sqlite", check_same_thread=False)
    saver = SqliteSaver(checkpoint_connection)
    graph = make_graph(saver)
    mutation_lock = threading.RLock()

    @asynccontextmanager
    async def lifespan(app):
        yield
        checkpoint_connection.close()
        engine.dispose()

    app = FastAPI(title="TradePilot", version="0.1.0", lifespan=lifespan)
    app.state.Session, app.state.graph = Session, graph

    def authorize(x_api_key: str = Header(default="")):
        if not secrets.compare_digest(x_api_key, api_token):
            raise HTTPException(401, "无效的访问凭证")

    def load_case(session, case_id):
        row = session.get(CaseRow, case_id)
        if not row:
            raise HTTPException(404, "案例不存在")
        return row, json.loads(row.payload)

    def load_run(session, case_id, run_id):
        row = session.get(RunRow, run_id)
        if not row or row.case_id != case_id:
            raise HTTPException(404, "审查不存在")
        return row, json.loads(row.payload)

    def execute(run_id, resume=False):
        with mutation_lock:
            with Session() as s:
                row = s.get(RunRow, run_id)
                payload = json.loads(row.payload)
                if resume:
                    current, _ = load_case(s, row.case_id)
                    if current.revision != row.revision:
                        row.status = "stale"
                        s.commit()
                        return
                row.status = "running"
                s.commit()
            try:
                result = graph.invoke(Command(resume={"approved": True}) if resume else payload["input"],
                                      {"configurable": {"thread_id": run_id}})
                with Session() as s:
                    row = s.get(RunRow, run_id)
                    payload = json.loads(row.payload)
                    payload.update({k: v for k, v in result.items() if not k.startswith("__")})
                    previous = s.get(RunRow, payload.get("previous_run_id")) if payload.get("previous_run_id") else None
                    payload["revision_delta"] = compare_runs(run_dict(previous) if previous else None,
                                                            {"id": row.id, "revision": row.revision, **payload})
                    row.status = "approved" if result.get("approved") else "awaiting_review"
                    row.payload = encode(payload)
                    case, body = load_case(s, row.case_id)
                    if case.revision == row.revision:
                        body["status"] = "archived" if result.get("approved") else "awaiting_review"
                        for reviewed in result.get("documents", []):
                            original = next((d for d in body["documents"] if d["id"] == reviewed["id"]), None)
                            if original:
                                fields = {f["field"] for f in original["facts"]}
                                original["facts"] += [f for f in reviewed["facts"] if f["field"] not in fields]
                        case.payload = encode(body)
                    if result.get("approved"):
                        case, body = load_case(s, row.case_id)
                        body["status"] = "archived"
                        body["audit"].append({"action": "archive", "run_id": run_id, "at": now()})
                        case.payload = encode(body)
                    s.commit()
            except Exception as exc:
                with Session() as s:
                    row = s.get(RunRow, run_id)
                    payload = json.loads(row.payload)
                    payload["error"] = type(exc).__name__ + ": " + str(exc)[:500]
                    row.status, row.payload = "failed", encode(payload)
                    s.commit()

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.1.0", "model_configured": bool(os.getenv("TRADEPILOT_MODEL_URL"))}

    @app.get("/cases", dependencies=[Depends(authorize)])
    def list_cases():
        with Session() as s:
            return [case_dict(r) for r in s.scalars(select(CaseRow).order_by(CaseRow.created_at.desc()))]

    @app.post("/cases", dependencies=[Depends(authorize)], status_code=201)
    def new_case(body: NewCase):
        with mutation_lock, Session() as s:
            row = CaseRow(payload=encode({**body.model_dump(), "documents": [], "reference_ids": [], "audit": [], "status": "draft"}))
            s.add(row)
            s.commit()
            return case_dict(row)

    @app.get("/cases/{case_id}", dependencies=[Depends(authorize)])
    def get_case(case_id: str):
        with Session() as s:
            row, _ = load_case(s, case_id)
            result = case_dict(row)
            result["runs"] = [run_dict(r) for r in s.scalars(select(RunRow).where(RunRow.case_id == case_id).order_by(RunRow.created_at.desc()))]
            return result

    @app.post("/cases/{case_id}/documents", dependencies=[Depends(authorize)])
    def upload(case_id: str, kind: str = Form(...), reference: bool = Form(False), file: UploadFile = File(...)):
        if kind not in {"inquiry", "quote", "order", "contract"}:
            raise HTTPException(422, "无效的文件类型")
        content = file.file.read(10 * 1024**2 + 1)
        if len(content) > 10 * 1024**2:
            raise HTTPException(413, "最多上传 10MB 文件")
        try:
            blocks, warnings = parse_document(file.filename or "document.txt", content)
        except Exception as exc:
            raise HTTPException(422, f"文件解析失败：{type(exc).__name__} {str(exc)[:160]}") from exc
        digest = hashlib.sha256(content).hexdigest()
        with mutation_lock, Session() as s:
            row, body = load_case(s, case_id)
            for doc in body["documents"]:
                if doc["sha256"] == digest and doc["kind"] == kind:
                    return doc
            doc_id = uid()
            folder = data / "files" / case_id
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / doc_id
            path.write_bytes(content)
            doc = {"id": doc_id, "name": Path(file.filename or "document.txt").name, "kind": kind,
                   "version": 1 + sum(d["kind"] == kind for d in body["documents"]), "sha256": digest,
                   "blocks": blocks, "warnings": warnings, "created_at": now()}
            doc["facts"] = extract(doc)
            doc["line_items"] = extract_items(doc)
            body["documents"].append(doc)
            if reference:
                body["reference_ids"].append(doc_id)
            body["status"] = "draft"
            body["audit"].append({"action": "upload", "document_id": doc_id, "at": now()})
            row.revision += 1
            row.payload = encode(body)
            s.commit()
            return doc

    @app.put("/cases/{case_id}/references", dependencies=[Depends(authorize)])
    def references(case_id: str, ids: list[str]):
        with mutation_lock, Session() as s:
            row, body = load_case(s, case_id)
            if not set(ids).issubset({d["id"] for d in body["documents"]}):
                raise HTTPException(422, "参考文件必须属于当前案例")
            body["reference_ids"], body["status"] = list(dict.fromkeys(ids)), "draft"
            row.revision += 1
            row.payload = encode(body)
            s.commit()
            return case_dict(row)

    @app.put("/cases/{case_id}/policy", dependencies=[Depends(authorize)])
    def policy(case_id: str, p: Policy):
        with mutation_lock, Session() as s:
            row, body = load_case(s, case_id)
            body["policy"], body["status"] = p.model_dump(), "draft"
            body["audit"].append({"action": "policy", "policy": p.model_dump(), "at": now()})
            row.revision += 1
            row.payload = encode(body)
            s.commit()
            return case_dict(row)

    @app.patch("/cases/{case_id}/documents/{doc_id}/facts/{fact_id}", dependencies=[Depends(authorize)])
    def correct(case_id: str, doc_id: str, fact_id: str, change: Correction):
        with mutation_lock, Session() as s:
            row, body = load_case(s, case_id)
            doc = next((d for d in body["documents"] if d["id"] == doc_id), None)
            fact = next((f for f in doc["facts"] if f["id"] == fact_id), None) if doc else None
            if not fact:
                raise HTTPException(404, "字段不存在")
            try:
                value = normalize(fact["field"], change.value)
            except Exception as exc:
                raise HTTPException(422, "字段格式无效") from exc
            body["audit"].append({"action": "correction", "document_id": doc_id, "fact_id": fact_id,
                                  "before": fact["value"], "after": value, "reason": change.reason, "at": now()})
            fact["value"], fact["confirmed"] = value, True
            row.revision += 1
            body["status"], row.payload = "draft", encode(body)
            s.commit()
            return fact

    @app.post("/cases/{case_id}/runs", dependencies=[Depends(authorize)], status_code=202)
    def start_run(case_id: str, tasks: BackgroundTasks):
        with mutation_lock, Session() as s:
            case, body = load_case(s, case_id)
            if not body["documents"]:
                raise HTTPException(422, "请先上传材料")
            active = s.scalar(select(RunRow).where(RunRow.case_id == case_id, RunRow.revision == case.revision, RunRow.status.in_(["queued", "running", "awaiting_review", "approved"])))
            if active:
                return run_dict(active)
            # Latest contract only; explicit reference versions remain pinned.
            contracts = [d for d in body["documents"] if d["kind"] == "contract"]
            selected = [d for d in body["documents"] if d["id"] in body["reference_ids"] and d["kind"] != "contract"]
            if contracts:
                selected.append(contracts[-1])
            knowledge_path = Path(__file__).resolve().parents[1] / "data/knowledge.json"
            knowledge_snapshot = hashlib.sha256(knowledge_path.read_bytes()).hexdigest() if knowledge_path.exists() else "none"
            snapshot = {"documents": selected, "reference_ids": body["reference_ids"], "policy": body["policy"], "knowledge_snapshot": knowledge_snapshot}
            previous = s.scalar(select(RunRow).where(RunRow.case_id == case_id,
                RunRow.status.in_(["awaiting_review", "approved"])).order_by(RunRow.created_at.desc()))
            run = RunRow(case_id=case_id, revision=case.revision, payload=encode({"input": snapshot, "decisions": {},
                "previous_run_id": previous.id if previous else None,
                "model": os.getenv("TRADEPILOT_MODEL_NAME", "rules-only"), "prompt_version": "review-v1", "rule_version": "seller-rules-v2", "validator_version": "evidence-v2-bilateral", "knowledge_snapshot": knowledge_snapshot, "limits": "single-tenant-prototype"}))
            s.add(run)
            body["status"] = "running"
            case.payload = encode(body)
            s.commit()
            tasks.add_task(execute, run.id)
            return run_dict(run)

    @app.get("/cases/{case_id}/runs/{run_id}", dependencies=[Depends(authorize)])
    def get_run(case_id: str, run_id: str):
        with Session() as s:
            run, _ = load_run(s, case_id, run_id)
            return run_dict(run)

    @app.get("/cases/{case_id}/runs/{run_id}/events", dependencies=[Depends(authorize)])
    def events(case_id: str, run_id: str):
        import time
        with Session() as s:
            load_run(s, case_id, run_id)
        def stream():
            for _ in range(180):
                with Session() as s:
                    row, _ = load_run(s, case_id, run_id)
                    value = run_dict(row)
                yield "data: " + encode(value) + "\n\n"
                if value["status"] not in {"queued", "running"}:
                    break
                time.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/cases/{case_id}/runs/{run_id}/decisions/{finding_id}", dependencies=[Depends(authorize)])
    def decide(case_id: str, run_id: str, finding_id: str, decision: DecisionInput):
        with mutation_lock, Session() as s:
            case, _ = load_case(s, case_id)
            run, payload = load_run(s, case_id, run_id)
            if run.revision != case.revision or run.status != "awaiting_review":
                raise HTTPException(409, "当前审查已过期或不可处理，请重新审查")
            if not any(f["id"] == finding_id for f in payload["findings"]):
                raise HTTPException(404, "问题不存在")
            entry = {**decision.model_dump(), "at": now(), "actor": "workspace-user"}
            payload["decisions"][finding_id] = entry
            payload.setdefault("decision_history", []).append({"finding_id": finding_id, **entry})
            run.payload = encode(payload)
            s.commit()
            return entry

    @app.post("/cases/{case_id}/runs/{run_id}/approve", dependencies=[Depends(authorize)])
    def approve(case_id: str, run_id: str, acknowledgement: ApprovalInput):
        with mutation_lock, Session() as s:
            case, _ = load_case(s, case_id)
            run, payload = load_run(s, case_id, run_id)
            if case.revision != run.revision:
                raise HTTPException(409, "材料或策略已变化，必须重新审查")
            if run.status == "approved":
                return run_dict(run)
            if run.status != "awaiting_review":
                raise HTTPException(409, "审查尚未完成")
            unresolved = [f for f in payload["findings"] if payload["decisions"].get(f["id"], {}).get("action") not in {"accept", "dismiss"}]
            if unresolved:
                raise HTTPException(409, "存在未处理问题或模型覆盖限制，暂不能归档")
            if payload.get("limitations") and not (acknowledgement.acknowledge_limitations and acknowledgement.reason.strip()):
                raise HTTPException(409, "请明确确认覆盖范围限制并记录人工复核理由")
            payload["approval"] = {**acknowledgement.model_dump(), "at": now(), "actor": "workspace-user"}
            run.payload = encode(payload)
            s.commit()
        execute(run_id, resume=True)
        return get_run(case_id, run_id)

    @app.post("/cases/{case_id}/runs/{run_id}/resume", dependencies=[Depends(authorize)])
    def retry(case_id: str, run_id: str, tasks: BackgroundTasks):
        with mutation_lock, Session() as s:
            case, _ = load_case(s, case_id)
            run, _ = load_run(s, case_id, run_id)
            if run.revision != case.revision or run.status not in {"failed", "running"}:
                raise HTTPException(409, "仅可恢复相同材料版本的失败或中断任务")
            run.status = "queued"
            s.commit()
            tasks.add_task(execute, run_id)
            return {"status": "queued"}

    @app.get("/cases/{case_id}/runs/{run_id}/export/{fmt}", dependencies=[Depends(authorize)])
    def download(case_id: str, run_id: str, fmt: str):
        with Session() as s:
            case, _ = load_case(s, case_id)
            run, payload = load_run(s, case_id, run_id)
            if fmt == "json":
                return Response(encode({"case_id": case_id, "run": run_dict(run)}), media_type="application/json",
                                headers={"Content-Disposition": f'attachment; filename="review-{run_id}.json"'})
            try:
                content, mime = export({"title": case_dict(case)["title"]}, run_dict(run), fmt)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="review-{run_id}.{fmt}"'})

    @app.post("/demo", dependencies=[Depends(authorize)])
    def demo(variant: str = "conflict"):
        from io import BytesIO
        from .demos import demo_documents
        if variant not in {"normal", "conflict", "missing"}:
            raise HTTPException(422, "无效的演示类型")
        case = new_case(NewCase(title={"normal": "正常交易", "conflict": "报价与合同条件变化", "missing": "材料不足"}[variant], description="程序生成的虚构演示材料，非真实客户数据"))
        for kind, name, content in demo_documents(variant):
            upload(case["id"], kind, kind == "quote", UploadFile(file=BytesIO(content.encode()), filename=name))
        return get_case(case["id"])

    app.state.execute = execute
    return app


def app_factory():
    return create_app()
