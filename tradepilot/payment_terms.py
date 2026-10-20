"""Conservative English payment-term patterns; never guess an absent trigger or credit period."""
import re

NUMBER = r"\d+(?:\.\d+)?"
EVENT = r"(?:receipt\s+of\s+(?:the\s+)?goods|goods\s+receipt|invoice(?:\s+(?:date|issuance))?|shipment|shipping|delivery|acceptance|bill\s+of\s+lading(?:\s+(?:date|copy))?)"
DEPOSITS = [
    re.compile(rf"\b(?P<value>{NUMBER})\s*%\s*(?:as\s+)?(?:an?\s+)?(?:advance\s+payment|deposit|prepayment|in\s+advance)\b", re.I),
    re.compile(rf"\b(?:deposit|prepayment|advance\s+payment)\s+(?:(?:of|equal\s+to)\s+)?(?P<value>{NUMBER})\s*%", re.I),
]
DAYS = [
    re.compile(rf"\b(?:balance|remaining\s+(?:amount|{NUMBER}\s*%)|final\s+payment)\b[^.;\n]{{0,80}}?\b(?:within\s+)?(?P<value>\d+)\s*(?:calendar\s+)?days?\s+(?:after|from|following)\s+(?P<event>{EVENT})\b", re.I),
    re.compile(rf"\b(?:payment\s+(?:is\s+)?due|payable|net)\s*:?\s*(?:within\s+)?(?P<value>\d+)\s*(?:calendar\s+)?days?\s+(?:after|from|following)\s+(?P<event>{EVENT})\b", re.I),
]
QUALIFIED = re.compile(r"\b(?:up\s+to|at\s+least|at\s+most|minimum(?:\s+of)?|maximum(?:\s+of)?|not\s+less\s+than|no\s+more\s+than)\s*$", re.I)
RANGE = re.compile(r"\d+(?:\.\d+)?\s*%?\s*(?:-|–|—|to)\s*$", re.I)
SUBPORTION = re.compile(r"\b(?:refund|return|interest|discount|penalty|tax)\s+(?:of\s+)?(?:the\s+)?$", re.I)
ALTERNATIVE = re.compile(r"\b(?:if|unless|otherwise|either|alternatively)\b", re.I)


def canonical_trigger(text):
    text = " ".join(text.casefold().split()).strip(" .")
    text = re.sub(r"^(?:after|from|following)\s+", "", text)
    aliases = {"shipping": "shipment", "invoice date": "invoice", "invoice issuance": "invoice",
               "receipt of goods": "delivery", "receipt of the goods": "delivery", "goods receipt": "delivery"}
    return aliases.get(text, text)


def extract_payment_terms(text):
    """Return field/value/quote triples and coverage warnings, without assessing legal risk."""
    facts, warnings = [], []
    if not re.search(r"\b(?:payment|deposit|prepayment|balance|payable|net)\b", text, re.I):
        return facts, warnings
    if ALTERNATIVE.search(text):
        return facts, ["付款条款包含条件或替代方案，需要人工确认，未自动确定付款条件。"]
    seen = set()
    def add(field, value, quote):
        key = field, value, quote
        if key not in seen:
            facts.append({"field": field, "value": value, "raw": quote, "quote": quote}); seen.add(key)
    for pattern in DEPOSITS:
        for match in pattern.finditer(text):
            prefix = text[max(0, match.start() - 35):match.start()]
            if QUALIFIED.search(prefix) or RANGE.search(prefix) or SUBPORTION.search(prefix):
                warnings.append("预付款表述为范围或上下限，未作为唯一比例；请人工校对。")
                continue
            add("deposit_percent", match.group("value"), match.group())
    for pattern in DAYS:
        for match in pattern.finditer(text):
            # Avoid consuming a separate inspection/claim term after a payment clause.
            prefix = text[max(0, match.start("value") - 35):match.start("value")]
            if QUALIFIED.search(prefix) or RANGE.search(prefix):
                warnings.append("账期表述为范围或上下限，未作为唯一账期；请人工校对。")
                continue
            if re.search(r"\b(?:inspection|warranty|claim|penalty|discount|interest|refund)\b", text[max(0, match.start() - 20):match.end()], re.I):
                continue
            add("payment_days", match.group("value"), match.group())
            add("payment_trigger", canonical_trigger(match.group("event")), match.group())
    return facts, list(dict.fromkeys(warnings))
