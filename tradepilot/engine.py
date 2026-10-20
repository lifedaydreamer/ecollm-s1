"""Deterministic baseline. Semantic interpretation is a separately labelled model step."""
import re
from decimal import Decimal, InvalidOperation
from .schema import Evidence, Fact, Finding, Policy

PATTERNS = {
    "seller": r"\bSeller\s*:\s*(.+)",
    "buyer": r"\bBuyer\s*:\s*(.+)",
    "currency": r"\bCurrency\s*:\s*([A-Z]{3})",
    "total": r"\b(?:Grand total|Total amount|Total)\s*:\s*(?:[A-Z]{3}\s*)?([\d,.]+)",
    "quantity": r"\bQuantity\s*:\s*([\d,.]+)",
    "deposit_percent": r"\b(?:Deposit|Prepayment)\s*:\s*([\d.]+)\s*%",
    "payment_days": r"\b(?:Balance due|Payment due|Payment days)\s*:\s*(\d+)\s*(?:days)?",
    "payment_trigger": r"\bPayment trigger\s*:\s*(.+)",
    "shipment_date": r"\bShipment date\s*:\s*(\d{4}-\d{2}-\d{2})",
    "delivery_date": r"\bDelivery date\s*:\s*(\d{4}-\d{2}-\d{2})",
    "incoterm": r"\bIncoterms?\s*:\s*(.+)",
    "inspection": r"\bInspection\s*:\s*(.+)",
    "liability": r"\bLiability\s*:\s*(.+)",
    "dispute": r"\bDispute resolution\s*:\s*(.+)",
}
NUMERIC = {"total", "quantity", "deposit_percent", "payment_days"}
ITEM_PATTERN = re.compile(r"SKU:\s*([^|]+)\|\s*Quantity:\s*([\d,.]+)\s*\|\s*(?:Unit:\s*([^|]+)\|\s*)?Unit price:\s*([A-Z]{3})\s*([\d,.]+)\s*\|\s*Line total:\s*([A-Z]{3})\s*([\d,.]+)\s*$", re.I)
LABELS = {"seller": "卖方", "buyer": "买方", "currency": "币种", "total": "总额",
          "quantity": "数量", "deposit_percent": "预付款比例", "payment_days": "账期",
          "shipment_date": "装运日期", "delivery_date": "交付日期", "incoterm": "贸易术语",
          "payment_trigger": "付款触发条件", "inspection": "验收", "liability": "责任", "dispute": "争议解决"}


def normalize(field, value):
    value = str(value).strip()
    if not value:
        raise ValueError("字段不能为缺少依据的空值")
    if field in NUMERIC:
        if not re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?", value):
            raise ValueError("请使用明确的英文数字分组与小数格式")
        number = Decimal(value.replace(",", "").replace("%", ""))
        if not number.is_finite() or number < 0:
            raise ValueError("金额、数量与比例必须为非负有限值")
        if field == "deposit_percent" and number > 100:
            raise ValueError("预付款比例不能超过 100%")
        if field == "payment_days" and number != number.to_integral_value():
            raise ValueError("账期必须为整数天")
        return format(number.normalize(), "f")
    if field.endswith("_date"):
        from datetime import date
        return date.fromisoformat(value).isoformat()
    return " ".join(value.split())


def extract_explicit(doc):
    facts = []
    for block in doc["blocks"]:
        for field, pattern in PATTERNS.items():
            if field in {"quantity", "total"} and re.search(r"\bSKU:", block["text"], re.I):
                continue  # Line quantities/amounts are not document-level totals.
            match = re.search(pattern, block["text"], re.I)
            if match:
                raw = match.group(1).split("|")[0].strip()
                try:
                    value = normalize(field, raw)
                except (ValueError, InvalidOperation):
                    warning = f"字段 {field} 无法可靠标准化，请校对原文。"
                    if warning not in doc.setdefault("warnings", []):
                        doc["warnings"].append(warning)
                    continue
                facts.append(Fact(field=field, raw=raw, value=value,
                    evidence=Evidence(document_id=doc["id"], block_id=block["id"],
                                      quote=block["text"], location=block["location"])).model_dump())
    return facts


def extract(doc):
    from .payment_terms import extract_payment_terms, canonical_trigger
    facts = extract_explicit(doc)
    for fact in facts:
        if fact["field"] == "payment_trigger":
            fact["value"] = canonical_trigger(fact["value"])
    for block in doc["blocks"]:
        candidates, warnings = extract_payment_terms(block["text"])
        if any("条件或替代方案" in warning for warning in warnings):
            facts = [f for f in facts if f["evidence"]["block_id"] != block["id"] or f["field"] not in {"deposit_percent", "payment_days", "payment_trigger"}]
        elif any("范围或上下限" in warning for warning in warnings):
            facts = [f for f in facts if f["evidence"]["block_id"] != block["id"] or f["field"] != "deposit_percent"]
        for warning in warnings:
            if warning not in doc.setdefault("warnings", []):
                doc["warnings"].append(warning)
        if any("账期表述为范围" in warning for warning in warnings):
            facts = [f for f in facts if f["evidence"]["block_id"] != block["id"] or f["field"] not in {"payment_days", "payment_trigger"}]
        for candidate in candidates:
            try:
                value = normalize(candidate["field"], candidate["value"])
            except (ValueError, InvalidOperation):
                warning = f"字段 {candidate['field']} 无法可靠标准化，请校对原文。"
                if warning not in doc.setdefault("warnings", []): doc["warnings"].append(warning)
                continue
            if any(f["field"] == candidate["field"] and f["value"] == value and f["evidence"]["block_id"] == block["id"] for f in facts):
                continue
            facts.append(Fact(field=candidate["field"], raw=candidate["raw"], value=value,
                evidence=Evidence(document_id=doc["id"], block_id=block["id"], quote=candidate["quote"],
                                  location=block["location"])).model_dump())
    return facts


def extract_items(doc):
    items = []
    for block in doc["blocks"]:
        start = re.search(r"\bSKU:", block["text"], re.I)
        if not start:
            continue
        evidence = {"document_id": doc["id"], "block_id": block["id"], "quote": block["text"], "location": block["location"]}
        match = ITEM_PATTERN.fullmatch(block["text"][start.start():].strip())
        if not match:
            items.append({"error": "行项目格式或数值不完整，请人工核对", "evidence": evidence})
            continue
        sku, qty, unit, currency, price, total_currency, total = match.groups()
        try:
            items.append({"sku": sku.strip(), "quantity": normalize("quantity", qty), "unit": (unit or "").strip(),
                          "currency": currency.upper(), "unit_price": normalize("total", price),
                          "total_currency": total_currency.upper(), "line_total": normalize("total", total), "evidence": evidence})
        except ValueError:
            items.append({"error": "行项目数字格式有歧义，请人工核对", "evidence": evidence})
    return items


def compare_items(reference, target):
    issues = []
    left, right = extract_items(reference), extract_items(target)
    for sku in sorted({i["sku"] for i in left + right if "sku" in i}):
        a, b = [i for i in left if i.get("sku") == sku], [i for i in right if i.get("sku") == sku]
        key = f"item:{reference['id']}:{sku}"
        if len(a) != 1 or len(b) != 1:
            issues.append(make_finding(key + ":mapping", "missing_info", f"{sku} 商品对应关系待确认",
                "SKU 未唯一对应；可能缺失、重复或使用了另一种标识。", "人工确认商品对应关系；系统不自动猜测替代商品。", a + b))
            continue
        a, b = a[0], b[0]
        if not a["unit"] or not b["unit"] or a["unit"].casefold() != b["unit"].casefold():
            issues.append(make_finding(key + ":unit", "missing_info", f"{sku} 计量单位待确认",
                f"参考单位 {a['unit'] or '未提供'}；合同单位 {b['unit'] or '未提供'}。", "明确单位和换算关系后再比较数量与单价。", [a, b]))
            continue
        for field, label in [("quantity", "数量"), ("unit_price", "单价")]:
            if field == "unit_price" and a["currency"] != b["currency"]:
                issues.append(make_finding(key + ":currency", "missing_info", f"{sku} 单价币种不同",
                    f"{a['currency']} 与 {b['currency']} 无法直接比较。", "补充汇率、时间和换算口径后人工核对。", [a, b]))
            elif a[field] != b[field]:
                issues.append(make_finding(key + ":" + field, "difference", f"{sku} {label}发生变化",
                    f"{reference['name']}：{a[field]}；{target['name']}：{b[field]}。", "确认商品规格和双方接受的条件。", [a, b], "info"))
    return issues


def evidence_valid(evidence, documents):
    for doc in documents:
        if doc["id"] == evidence["document_id"]:
            return any(b["id"] == evidence["block_id"] and bool(evidence["quote"].strip())
                       and evidence["quote"] in b["text"] for b in doc["blocks"])
    return False


def unique_fact(doc, field):
    matches = [f for f in doc.get("facts", []) if f["field"] == field]
    if len({f["value"] for f in matches}) == 1 and matches:
        return matches[0]
    return None


def make_finding(key, kind, title, explanation, suggestion, facts=(), severity="medium"):
    return Finding(key=key, kind=kind, severity=severity, title=title,
                   explanation=explanation, suggestion=suggestion,
                   evidence=[Evidence.model_validate(f["evidence"]) for f in facts]).model_dump()


def compare_documents(documents, reference_ids):
    issues = []
    contracts = [d for d in documents if d["kind"] == "contract"]
    if not contracts:
        return [make_finding("missing:contract", "missing_info", "缺少待审合同", "尚未选择合同版本。", "上传合同后重审。")]
    target = contracts[-1]
    references = [d for d in documents if d["id"] in reference_ids and d["id"] != target["id"]]
    if not references:
        issues.append(make_finding("missing:reference", "missing_info", "尚未指定参考材料", "跨文档比较需要明确参考报价或订单。", "在文档列表选择参考文件。"))
    for ref in references:
        issues.extend(compare_items(ref, target))
        for field in PATTERNS:
            left, right = unique_fact(ref, field), unique_fact(target, field)
            if left and right and left["value"].casefold() != right["value"].casefold():
                issues.append(make_finding(f"difference:{ref['id']}:{field}", "difference",
                    f"{LABELS[field]}发生变化", f"{ref['name']}：{left['value']}；{target['name']}：{right['value']}。",
                    "核对是否为双方有意修改，确认后保留处理理由。", [left, right], severity="info"))
    return issues


def policy_review(documents, policy):
    p = Policy.model_validate(policy)
    issues = []
    for doc in documents:
        if doc["kind"] != "contract":
            continue
        for field in ("seller", "buyer", "currency", "total", "deposit_percent", "payment_days"):
            if not unique_fact(doc, field):
                issues.append(make_finding(f"missing:{doc['id']}:{field}", "missing_info", f"请核实{LABELS[field]}",
                    "规则提取未得到唯一值；可能是表述未覆盖、字段缺失或存在多处取值。", "查看完整原文并补充或校对字段。"))
        for field, limit, op, title in [
            ("deposit_percent", p.min_deposit_percent, "min", "预付款低于企业策略"),
            ("payment_days", p.max_payment_days, "max", "账期超出企业策略"),
        ]:
            fact = unique_fact(doc, field)
            if fact and ((op == "min" and Decimal(fact["value"]) < Decimal(str(limit))) or
                         (op == "max" and Decimal(fact["value"]) > Decimal(str(limit)))):
                issue = make_finding(f"policy:{doc['id']}:{field}", "business_risk", title,
                    f"当前值 {fact['value']}；企业策略 {p.version} 的阈值为 {limit}。",
                    "与业务负责人确认，形成修改建议或记录例外接受理由。", [fact], "high")
                issue["basis"] = [{"title": p.version, "type": "enterprise_policy", "value": limit}]
                issues.append(issue)
        # Explicit line items are checked independently; totals with unidentified fees are not equated.
        for item in extract_items(doc):
            block_id = item["evidence"]["block_id"]
            if item.get("error"):
                issues.append(make_finding(f"item-invalid:{doc['id']}:{block_id}", "missing_info", "行项目需要人工校对", item["error"], "补充完整 SKU、数量、单位、单价和行金额。", [item]))
            elif item["currency"] != item["total_currency"]:
                issues.append(make_finding(f"currency:{doc['id']}:{block_id}", "missing_info", "行项目币种不同", "无法直接执行金额核对。", "统一币种或补充换算依据。", [item]))
            elif Decimal(item["quantity"]) * Decimal(item["unit_price"]) != Decimal(item["line_total"]):
                issues.append(make_finding(f"arithmetic:{doc['id']}:{block_id}", "business_risk", f"{item['sku']} 行金额不一致", "数量乘单价与行金额不一致。", "核对单价、数量和该行折扣或费用、舍入约定。", [item], "high"))
    return issues


def review(documents, reference_ids, policy):
    issues = compare_documents(documents, reference_ids) + policy_review(documents, policy)
    for doc in documents:
        for index, warning in enumerate(doc.get("warnings", [])):
            issues.append(make_finding(f"parse:{doc['id']}:{index}", "missing_info", "文档解析需核验", warning,
                                      "补充可识别文本或完成 OCR 后重新审查。"))
    return issues
