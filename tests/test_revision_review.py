import io
import httpx
from fastapi.testclient import TestClient
from tradepilot.api import create_app
from tradepilot.demos import demo_documents
from tradepilot.model import analyze_remote
from tradepilot.schema import AnalyzeRequest
from tradepilot.knowledge import KnowledgeStore, finding_topics
from pathlib import Path


def test_revision_removes_detections_without_inheriting_approval(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADEPILOT_MODEL_URL", raising=False)
    with TestClient(create_app(data_dir=tmp_path, token="test"), headers={"X-API-Key":"test"}) as client:
        case = client.post("/demo?variant=conflict").json()
        prefix = f"/cases/{case['id']}/runs"
        old = client.post(prefix).json()
        old = client.get(prefix + "/" + old["id"]).json()
        issue = old["findings"][0]
        client.post(prefix+f"/{old['id']}/decisions/{issue['id']}", json={"action":"accept","reason":"仅对旧版确认"}).raise_for_status()
        content = demo_documents("normal")[-1][2]
        client.post(f"/cases/{case['id']}/documents", data={"kind":"contract"}, files={"file":("revised.txt",content.encode())}).raise_for_status()
        new = client.post(prefix).json()
        new = client.get(prefix + "/" + new["id"]).json()
        delta = new["revision_delta"]
        assert delta["previous_run_id"] == old["id"]
        assert delta["comparable"] is True
        assert len(delta["not_redetected"]) == 5
        assert not delta["added"] and not delta["repeated"]
        assert new["decisions"] == {}
        assert client.get(prefix+"/"+old["id"]).json()["findings"] == old["findings"]
        assert client.post(prefix+"/"+old["id"]+"/approve",json={}).status_code == 409
        assert client.post(prefix+"/"+new["id"]+"/approve",json={}).status_code == 409


def test_policy_change_is_not_presented_as_contract_fix(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADEPILOT_MODEL_URL", raising=False)
    with TestClient(create_app(data_dir=tmp_path, token="test"), headers={"X-API-Key":"test"}) as client:
        case = client.post("/demo?variant=conflict").json()
        prefix = f"/cases/{case['id']}"
        old = client.post(prefix+"/runs").json()
        client.put(prefix+"/policy", json={"version":"relaxed-2","min_deposit_percent":0,"max_payment_days":90}).raise_for_status()
        new = client.post(prefix+"/runs").json()
        new = client.get(prefix+"/runs/"+new["id"]).json()
        delta = new["revision_delta"]
        assert delta["comparable"] is False
        assert "企业策略变化" in delta["notes"]
        assert len(delta["not_redetected"]) == 2
        assert len(delta["repeated"]) == 3


def test_compare_requires_two_documents_even_for_real_quotes(monkeypatch):
    docs = [{"id":ident,"kind":kind,"blocks":[{"id":"b1","text":"Deposit: 0%","location":"line 1"}]} for ident,kind in [("a","quote"),("b","contract")]]
    evidence = {"document_id":"b","block_id":"b1","quote":"Deposit: 0%"}
    finding = {"key":"payment","kind":"difference","severity":"info","title":"付款变化","explanation":"different","suggestion":"check","evidence":[evidence]}
    def fake(*a, **kw):
        return httpx.Response(200,json={"findings":[finding],"comparison":"different"},request=httpx.Request("POST","http://model"))
    monkeypatch.setattr(httpx,"post",fake)
    result = analyze_remote(AnalyzeRequest(task="compare",documents=docs),"http://model")
    assert result.findings == [] and result.comparison == "insufficient"
    finding["evidence"].append({**evidence,"document_id":"a"})
    result = analyze_remote(AnalyzeRequest(task="compare",documents=docs),"http://model")
    assert len(result.findings) == 1 and result.comparison == "different"


def test_retrieval_routing_preserves_source_and_scope():
    store = KnowledgeStore(Path(__file__).parents[1]/"data/knowledge.json")
    rows = store.search("贸易术语发生变化", topics=finding_topics({"key":"difference:doc:incoterm","title":"贸易术语发生变化"}))
    assert any(r["id"] == "incoterms-reference" for r in rows)
    assert all("incoterm" in r["topics"] for r in rows)
    assert all(r["snapshot"] == store.snapshot and r["applicability"] for r in rows)
    assert not store.search("未知问题", topics=[])
