import json
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from tradepilot.api import create_app
from tradepilot.schema import AnalyzeResponse, Fact, Evidence
from tradepilot.workflow import make_graph
from tradepilot.engine import unique_fact
from tradepilot.db import RunRow, encode


def test_conflicting_model_facts_survive_workflow(monkeypatch):
    doc = {"id": "contract", "name": "contract.txt", "kind": "contract", "facts": [],
           "blocks": [{"id": "b1", "text": "Advance payment is 30%. Another section requires 50%.", "location": "line 1"}]}
    facts = [Fact(field="deposit_percent", raw=value + "%", value=value,
                  evidence=Evidence(document_id="contract", block_id="b1", quote=doc["blocks"][0]["text"]))
             for value in ("30", "50")]
    monkeypatch.setattr("tradepilot.workflow.analyze_remote", lambda request:
                        AnalyzeResponse(facts=facts) if request.task == "extract" else AnalyzeResponse())
    graph = make_graph(InMemorySaver())
    result = graph.invoke({"documents": [doc], "reference_ids": [], "policy": {}},
                          {"configurable": {"thread_id": "conflict"}})
    reviewed = result["documents"][0]
    assert {f["value"] for f in reviewed["facts"]} == {"30", "50"}
    assert unique_fact(reviewed, "deposit_percent") is None
    assert any(f["key"] == "missing:contract:deposit_percent" for f in result["findings"])


def test_correcting_archived_case_resets_state_and_replayed_approval_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADEPILOT_MODEL_URL", raising=False)
    app = create_app(data_dir=tmp_path, token="test")
    with TestClient(app, headers={"X-API-Key": "test"}) as client:
        case = client.post("/demo?variant=normal").json()
        prefix = f"/cases/{case['id']}"
        run = client.post(prefix + "/runs").json()
        path = prefix + "/runs/" + run["id"]
        assert client.post(path + "/approve", json={"acknowledge_limitations": True, "reason": "人工核验"}).json()["status"] == "approved"
        app.state.execute(run["id"], resume=True)
        after = client.get(prefix).json()
        assert len([a for a in after["audit"] if a["action"] == "archive"]) == 1
        contract = after["documents"][-1]
        fact = next(f for f in contract["facts"] if f["field"] == "total")
        client.patch(prefix + f"/documents/{contract['id']}/facts/{fact['id']}",
                     json={"value": "95000", "reason": "校对原文"}).raise_for_status()
        assert client.get(prefix).json()["status"] == "draft"
        assert client.post(path + "/approve", json={}).status_code == 409
        assert client.get(path).json()["status"] == "approved"  # Historical snapshot unchanged.


def test_retry_cannot_archive_a_checkpoint_without_new_human_approval(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADEPILOT_MODEL_URL", raising=False)
    app = create_app(data_dir=tmp_path, token="test")
    with TestClient(app, headers={"X-API-Key": "test"}) as client:
        case = client.post("/demo?variant=normal").json()
        run = client.post(f"/cases/{case['id']}/runs").json()
        with app.state.Session() as session:
            row = session.get(RunRow, run["id"])
            payload = json.loads(row.payload)
            payload.update(error="interrupted", approval={"reason": "prior failed attempt"})
            row.status, row.payload = "failed", encode(payload)
            session.commit()
        original = app.state.graph.invoke
        observed = []
        def interrupted_checkpoint(value, config):
            observed.append(value)
            return {"approved": True}
        monkeypatch.setattr(app.state.graph, "invoke", interrupted_checkpoint)
        path = f"/cases/{case['id']}/runs/{run['id']}"
        client.post(path + "/resume").raise_for_status()
        failed = client.get(path).json()
        assert failed["status"] == "failed"
        assert "explicit human approval" in failed["error"]
        assert observed[0]["approved"] is False
        assert not failed.get("approval")
        assert client.get(f"/cases/{case['id']}").json()["status"] != "archived"
        monkeypatch.setattr(app.state.graph, "invoke", original)
        client.post(path + "/resume").raise_for_status()
        recovered = client.get(path).json()
        assert recovered["status"] == "awaiting_review"
        assert "error" not in recovered
