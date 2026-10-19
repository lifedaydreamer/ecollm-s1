from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field, ConfigDict


def uid():
    return uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Block(StrictModel):
    id: str
    text: str
    page: int | None = None
    location: str = ""
    bbox: list[float] | None = None


class Evidence(StrictModel):
    document_id: str
    block_id: str
    quote: str
    location: str = ""


class Fact(StrictModel):
    id: str = Field(default_factory=uid)
    field: str
    raw: str
    value: str
    evidence: Evidence
    confirmed: bool = False


class Finding(StrictModel):
    id: str = Field(default_factory=uid)
    key: str
    kind: Literal["difference", "business_risk", "missing_info"]
    severity: Literal["info", "medium", "high"]
    title: str
    explanation: str
    suggestion: str
    evidence: list[Evidence] = []
    basis: list[dict] = []
    origin: Literal["rule", "model"] = "rule"


class Policy(StrictModel):
    version: str = "seller-v1"
    min_deposit_percent: float = Field(default=30, ge=0, le=100)
    max_payment_days: int = Field(default=30, ge=0, le=365)


class NewCase(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    policy: Policy = Field(default_factory=Policy)


class DecisionInput(StrictModel):
    action: Literal["accept", "dismiss", "request_change"]
    reason: str = Field(min_length=1, max_length=2000)


class Correction(StrictModel):
    value: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=2000)


class ApprovalInput(StrictModel):
    acknowledge_limitations: bool = False
    reason: str = Field(default="", max_length=2000)


class AnalyzeRequest(StrictModel):
    task: Literal["extract", "review", "compare"]
    documents: list[dict] = Field(min_length=1, max_length=8)
    policy: Policy = Field(default_factory=Policy)


class AnalyzeResponse(StrictModel):
    facts: list[Fact] = []
    findings: list[Finding] = []
    comparison: Literal["consistent", "different", "insufficient"] = "insufficient"
    limitations: list[str] = []
