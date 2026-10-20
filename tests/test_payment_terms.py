from tradepilot.engine import extract, unique_fact, evidence_valid


def document(text):
    return {"id": "doc", "kind": "contract", "name": "contract.txt", "blocks": [{"id": "b1", "text": text, "location": "line 1"}]}


def test_plain_english_payment_terms_have_exact_evidence():
    doc = document("Payment terms: 30% as a deposit, balance 70% payable within 60 days after shipment.")
    doc["facts"] = extract(doc)
    assert unique_fact(doc, "deposit_percent")["value"] == "30"
    assert unique_fact(doc, "payment_days")["value"] == "60"
    assert unique_fact(doc, "payment_trigger")["value"] == "shipment"
    assert all(evidence_valid(f["evidence"], [doc]) for f in doc["facts"])


def test_ambiguous_payment_values_are_not_inferred():
    for text in ("Payment terms: up to 30% deposit.", "If approved, payment is 30% deposit, otherwise 50% deposit.",
                 "Inspection within 30 days after delivery.", "Payment terms: Deposit: 20-30%.",
                 "Payment terms: refund of 30% deposit.",
                 "Balance payable up to 60 days after shipment.",
                 "Balance payable 30-60 days after shipment.",
                 "Interest payable 30 days after invoice.",
                 "Payment terms: Deposit: 20%-30%.",
                 "Payment days: 30-60 days.",
                 "Payment days: 30 business days after shipment."):
        doc = document(text); doc["facts"] = extract(doc)
        assert not unique_fact(doc, "deposit_percent") and not unique_fact(doc, "payment_days")
    doc = document("Payment terms: deposit of 30%; a prepayment of 50% is also stated.")
    doc["facts"] = extract(doc)
    assert unique_fact(doc, "deposit_percent") is None


def test_natural_payment_changes_reach_policy_and_difference_checks():
    from tradepilot.engine import review
    common = "Seller: Acme\nBuyer: Buyer\nCurrency: USD\nTotal: USD 1000\n"
    texts = [common + "Payment terms: 30% deposit, balance within 30 days after shipment.",
             common + "Payment terms: 0% deposit, balance within 90 days after delivery."]
    docs = []
    for ident, kind, text in zip(("quote", "contract"), ("quote", "contract"), texts):
        doc = {"id": ident, "kind": kind, "name": ident, "blocks": [{"id": f"b{i}", "text": line, "location": f"line {i}"} for i, line in enumerate(text.splitlines(), 1)]}
        doc["facts"] = extract(doc); docs.append(doc)
    findings = review(docs, ["quote"], {})
    assert len([f for f in findings if f["kind"] == "difference"]) == 3
    assert len([f for f in findings if f["kind"] == "business_risk"]) == 2
    assert not [f for f in findings if f["kind"] == "missing_info"]
