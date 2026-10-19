import importlib.util
import json
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location("build_data",Path(__file__).parents[1]/"scripts/build_data.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_generated_labels_cannot_be_released_as_gold(tmp_path):
    module.generate(tmp_path,3)
    manifest=json.loads((tmp_path/"manifest.json").read_text())
    assert manifest["reviewed"]==0
    with pytest.raises(ValueError,match="人工审核"):
        module.release(tmp_path/"candidates.jsonl",tmp_path/"released")


def test_family_leakage_and_independent_review(tmp_path):
    module.generate(tmp_path,3)
    rows=[json.loads(x) for x in (tmp_path/"candidates.jsonl").read_text().splitlines()]
    for row in rows:
        row.update(review_status="approved",reviewer="reviewer-a",second_reviewer="reviewer-b")
    rows[1]["split"]="test"
    path=tmp_path/"reviewed.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in rows))
    with pytest.raises(ValueError,match="泄漏"):
        module.release(path,tmp_path/"released")
