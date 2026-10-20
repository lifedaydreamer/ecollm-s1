import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile
import pytest
from tradepilot.clause_task import messages, parse_prediction, score


def test_clause_output_needs_exact_nonempty_quotes_and_consistent_status():
    text="The seller maintains product liability insurance."
    value,grounded=parse_prediction(json.dumps({"status":"found","evidence":[text]}),text)
    assert grounded
    _,grounded=parse_prediction(json.dumps({"status":"found","evidence":["Not in the contract"]}),text)
    assert not grounded
    for value in [{"status":"found","evidence":[]},{"status":"not_found_in_excerpt","evidence":[text]},
                  {"status":"found","evidence":[text],"risk":"high"}]:
        with pytest.raises(ValueError):parse_prediction(json.dumps(value),text)


def test_extraction_scores_do_not_claim_risk_metrics():
    rows=[{"input":{"category":"Insurance","text":"insurance required"},"target":{"status":"found","evidence":["insurance required"]}},
          {"input":{"category":"Insurance","text":"nothing"},"target":{"status":"not_found_in_excerpt","evidence":[]}}]
    predictions=[{"output":r["target"],"schema_valid":True,"grounded":True} for r in rows]
    metrics=score(rows,predictions)
    assert metrics["mean_evidence_token_f1"]==metrics["clause_presence_macro_f1"]==1
    assert "not trade risk" in metrics["note"]
    predictions[0]={"schema_valid":False}
    assert score(rows,predictions)["mean_evidence_token_f1"]==0.5
    assert messages(rows[0])[1]["role"]=="user"


def test_cuad_conversion_preserves_labels_and_isolates_issuer(tmp_path,monkeypatch):
    script=Path(__file__).parents[1]/"ml/prepare_cuad.py"
    spec=importlib.util.spec_from_file_location("prepare_cuad",script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    def doc(title):
        text=title+"\n"+"Commercial background. "*8+"Supplier maintains insurance."
        quote="Supplier maintains insurance."
        return {"title":title,"paragraphs":[{"context":text,"qas":[{"id":title+"__Insurance","answers":[{"text":quote,"answer_start":text.index(quote)}]}]}]}
    test=doc("ISSUERA_test")
    documents=[test,doc("ISSUERA_amendment"),doc("ISSUERB_train"),doc("ISSUERC_train")]
    archive=tmp_path/"source.zip"
    with ZipFile(archive,"w") as z:
        z.writestr("CUADv1.json",json.dumps({"data":documents}));z.writestr("test.json",json.dumps({"data":[test]}))
    raw=archive.read_bytes();monkeypatch.setattr(module,"SOURCE_BLOB",hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest())
    manifest=module.prepare(archive,tmp_path/"output")
    assert manifest["audit"]["train_contracts_removed_due_to_test_issuer"]==1
    for split in ("train","validation","test"):
        for line in (tmp_path/"output"/(split+".jsonl")).read_text().splitlines():
            r=json.loads(line)
            assert all(q in r["input"]["text"] for q in r["target"]["evidence"])
            assert "risk" not in r["target"] and "reviewer" not in r
