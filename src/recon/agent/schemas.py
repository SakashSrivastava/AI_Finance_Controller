"""Verdict schemas.

These are enforced by the provider (`response_format` with a strict JSON schema), so a
malformed reply is impossible rather than merely discouraged. That removes a whole class
of parsing defensiveness - but it says nothing about whether the *content* is right,
which is what the gate is for.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["match", "no_match", "needs_human"]


class BankProposal(BaseModel):
    verdict: Verdict
    payment_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0


class InvoiceProposal(BaseModel):
    verdict: Verdict
    invoice_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0


def _schema(name: str, id_field: str) -> dict:
    return {
        "name": name,
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["match", "no_match", "needs_human"]},
                id_field: {"type": "array", "items": {"type": "string"}},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["verdict", id_field, "reasoning", "confidence"],
            "additionalProperties": False,
        },
    }


BANK_SCHEMA = _schema("bank_proposal", "payment_ids")
INVOICE_SCHEMA = _schema("invoice_proposal", "invoice_ids")
