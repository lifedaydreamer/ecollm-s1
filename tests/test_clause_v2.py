import json
from pathlib import Path
from tradepilot.clause_task import CATEGORIES, messages
from ml.prepare_clause_v2 import select


def test_optional_category_guidance_preserves_basic_prompt_and_exact_input():
    row = {"input": {"category": "Minimum Commitment", "text": "A minimum order is 100 units."}}
    basic = messages(row)
    guided = messages(row, with_definitions=True)
    assert guided[1] == basic[1]
    assert guided[0]["content"].startswith(basic[0]["content"])
    assert "minimum order size" in guided[0]["content"]
    definitions = json.loads((Path(__file__).parents[1] / "configs/cuad-category-definitions.json").read_text())
    assert set(definitions["definitions"]) == set(CATEGORIES)


def test_v2_sampling_keeps_real_labels_and_deduplicates_contexts():
    pool = [{"id": str(i), "input": {"category": "Insurance", "text": "insurance clause"},
             "target": {"evidence": ["insurance clause"] if i < 2 else []},
             "context_hash": str(i // 2)} for i in range(10)]
    selected = select(pool, 2, 4, hard_negative=True)
    assert len({r["context_hash"] for r in selected}) == len(selected)
    assert all(r in pool for r in selected)
    assert any(r["target"]["evidence"] for r in selected)
