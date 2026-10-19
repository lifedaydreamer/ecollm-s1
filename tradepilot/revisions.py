"""Conservative revision comparison. A missing detection is never an approval."""
from collections import defaultdict


def topic(finding, documents):
    key = finding["key"]
    if finding.get("origin") == "model":
        # Model keys include evidence IDs; match only exact titles, without fuzzy inference.
        return "model:" + finding["kind"] + ":" + " ".join(finding["title"].split()).casefold()
    for doc in documents:
        key = key.replace(doc["id"], "contract" if doc["kind"] == "contract" else "ref-" + doc["id"])
    return key


def compare_runs(previous, current):
    if previous is None:
        return {"previous_run_id": None, "comparable": False, "notes": ["首次审查，没有历史对照。"],
                "added": [], "repeated": [], "not_redetected": []}
    old_input, new_input = previous["input"], current["input"]
    notes = []
    checks = [("reference_ids", "参考文件选择变化"), ("policy", "企业策略变化"),
              ("knowledge_snapshot", "知识快照变化")]
    for key, label in checks:
        if old_input.get(key) != new_input.get(key):
            notes.append(label)
    for key in ("model", "prompt_version", "rule_version", "validator_version"):
        if previous.get(key) != current.get(key):
            notes.append(f"{key} 变化")
    if sorted(previous.get("limitations", [])) != sorted(current.get("limitations", [])):
        notes.append("审查覆盖范围变化")
    if any(d.get("warnings") for d in current.get("documents", [])):
        notes.append("当前材料存在解析提示")
    old, new = defaultdict(list), defaultdict(list)
    for f in previous.get("findings", []):
        old[topic(f, old_input["documents"])].append(f)
    for f in current.get("findings", []):
        new[topic(f, new_input["documents"])].append(f)
    result = {"previous_run_id": previous["id"], "previous_revision": previous["revision"],
              "comparable": not notes, "notes": notes, "added": [], "repeated": [], "not_redetected": []}
    for key in sorted(set(old) | set(new)):
        before, after = old[key], new[key]
        # Ambiguous repeated titles are deliberately left unmatched.
        if len(before) == len(after) == 1:
            result["repeated"].append({"title": after[0]["title"], "finding_id": after[0]["id"],
                                       "previous_finding_id": before[0]["id"]})
        else:
            result["added"].extend({"title": f["title"], "finding_id": f["id"]} for f in after)
            result["not_redetected"].extend({"title": f["title"], "previous_finding_id": f["id"]} for f in before)
    return result
