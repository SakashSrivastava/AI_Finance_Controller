"""Data contracts shared by the generator, matcher, agent, and evaluator."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field

TxnType = Literal["payment", "refund", "chargeback"]
InvoiceStatus = Literal["open", "paid", "partially_paid", "overdue"]
ResolvedBy = Literal["deterministic", "llm_verified"]


def _blank_to_none(v: Any) -> Any:
    return None if v == "" else v


def _split_pipe(v: Any) -> Any:
    if isinstance(v, str):
        return [part for part in v.split("|") if part]
    return v


OptionalPaise = Annotated[int | None, BeforeValidator(_blank_to_none)]
PipeList = Annotated[list[str], BeforeValidator(_split_pipe)]


class Invoice(BaseModel):
    invoice_id: str
    customer_id: str
    customer_name: str
    invoice_date: date
    due_date: date
    gross_amount_paise: int
    status: InvoiceStatus


class Settlement(BaseModel):
    payment_id: str
    invoice_ref: str
    customer_name: str
    captured_at: date
    settled_at: date
    utr: str
    gross_amount_paise: int
    fee_paise: int
    gst_on_fee_paise: int
    net_amount_paise: OptionalPaise = None
    type: TxnType


class BankTxn(BaseModel):
    txn_id: str
    value_date: date
    narration: str
    credit_paise: int = 0
    debit_paise: int = 0
    balance_paise: int = 0


class GroundTruthBank(BaseModel):
    bank_txn_id: str
    payment_ids: PipeList = Field(default_factory=list)
    case_tags: PipeList = Field(default_factory=list)


class GroundTruthInvoice(BaseModel):
    payment_id: str
    invoice_ids: PipeList = Field(default_factory=list)
    case_tags: PipeList = Field(default_factory=list)


class MatchRecord(BaseModel):
    bank_txn_id: str
    payment_ids: list[str] = Field(default_factory=list)
    invoice_ids: list[str] = Field(default_factory=list)
    tier: str
    confidence: float
    evidence: dict = Field(default_factory=dict)
    resolved_by: ResolvedBy


INVOICE_COLUMNS = [
    "invoice_id",
    "customer_id",
    "customer_name",
    "invoice_date",
    "due_date",
    "gross_amount_paise",
    "status",
]

SETTLEMENT_COLUMNS = [
    "payment_id",
    "invoice_ref",
    "customer_name",
    "captured_at",
    "settled_at",
    "utr",
    "gross_amount_paise",
    "fee_paise",
    "gst_on_fee_paise",
    "net_amount_paise",
    "type",
]

BANK_COLUMNS = ["txn_id", "value_date", "narration", "credit_paise", "debit_paise", "balance_paise"]

GT_BANK_COLUMNS = ["bank_txn_id", "payment_ids", "case_tags"]

GT_INVOICE_COLUMNS = ["payment_id", "invoice_ids", "case_tags"]
