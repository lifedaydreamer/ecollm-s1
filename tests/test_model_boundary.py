import httpx
from tradepilot.model import analyze_remote
from tradepilot.schema import AnalyzeRequest


def test_model_cannot_override_rule_ids_or_confirm_its_own_facts(monkeypatch):
    docs=[{"id":"doc","kind":"contract","blocks":[{"id":"b1","text":"Deposit: 0%","location":"line 1"}]}]
    evidence={"document_id":"doc","block_id":"b1","quote":"Deposit: 0%","location":"invented page 99"}
    issue={"id":"chosen-id","key":"policy:doc:deposit_percent","kind":"difference","severity":"high", "title":"Changed", "explanation":"Changed terms", "suggestion":"Confirm", "evidence":[evidence]}
    bad={**issue,"key":"fake","evidence":[{**evidence,"quote":"This never appeared"}]}
    response={"facts":[{"id":"chosen-id","field":"deposit_percent","raw":"0%","value":"0","evidence":evidence,"confirmed":True}],"findings":[issue,bad]}
    monkeypatch.setattr(httpx,"post",lambda *a,**k:httpx.Response(200,json=response,request=httpx.Request("POST","http://model/v1/analyze")))
    result=analyze_remote(AnalyzeRequest(task="review",documents=docs),"http://model")
    assert len(result.findings)==1
    assert result.findings[0].key.startswith("model:")
    assert result.findings[0].severity=="info"
    assert result.findings[0].id!="chosen-id"
    assert result.facts[0].confirmed is False
    assert result.facts[0].id!="chosen-id"
    assert result.facts[0].evidence.location == "line 1"
    assert result.findings[0].evidence[0].location == "line 1"
    assert any(x.startswith("已拒绝") for x in result.limitations)
