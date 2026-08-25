"""Read-only investigation tools the agent drives itself.

Every tool answers a question about the data. None of them change anything. The only
terminal action is `submit`, and what it submits still goes through the verification gate
afterwards — the agent proposes, it does not decide.

`test_combination` is the interesting one. It lets the agent check its own arithmetic
before committing, which is exactly what a human reconciler does. It also creates a
measurable question that a single-shot prompt cannot ask: **does the agent ever submit a
combination its own test told it does not close?** That gap between what a model verifies
and what it then asserts is the thing this project is about, observed from the inside.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from recon.domain.models import Invoice, Settlement
from recon.matcher.types import NormalisedSettlement

# Kept deliberately small. An agent turn resends the whole conversation, so every row a
# tool returns is paid for again on every subsequent turn. Wide tool output is the single
# biggest driver of token cost in a loop.
MAX_ROWS = 12


def tool_schemas(level: str) -> list[dict]:
    """Groq/OpenAI-compatible function definitions for one escalation level."""
    common = [
        {
            "type": "function",
            "function": {
                "name": "test_combination",
                "description": (
                    "Sum the net amounts of these settlements and compare with the bank "
                    "credit. Use this to check a hypothesis before submitting it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "payment_ids": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["payment_ids"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_batch",
                "description": (
                    "List every settlement sharing a UTR, including any withheld from the "
                    "payout, with net amounts and whether each is already attributed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"utr": {"type": "string"}},
                    "required": ["utr"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_settlements",
                "description": (
                    "Search unattributed settlements by settled date range and optional net "
                    "amount range. Use to widen or narrow the candidate pool."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days_before": {"type": "integer"},
                        "min_paise": {"type": "integer"},
                        "max_paise": {"type": "integer"},
                    },
                    "required": ["days_before"],
                },
            },
        },
    ]
    invoice = [
        {
            "type": "function",
            "function": {
                "name": "get_invoices_for_customer",
                "description": "List invoices belonging to a customer, with amounts and dates.",
                "parameters": {
                    "type": "object",
                    "properties": {"customer_name": {"type": "string"}},
                    "required": ["customer_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "test_invoice_set",
                "description": (
                    "Check whether these invoices could be settled by this payment: are they "
                    "the right customer, and does the payment exceed their total?"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "invoice_ids": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["invoice_ids"],
                },
            },
        },
    ]
    submit_bank = {
        "type": "function",
        "function": {
            "name": "submit",
            "description": (
                "Final answer. Submit the settlements that make up this credit, or verdict "
                "'no_match' if nothing fits. A wrong match is worse than no match."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string", "enum": ["match", "no_match", "needs_human"]},
                    "payment_ids": {"type": "array", "items": {"type": "string"}},
                    "reasoning": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["verdict", "payment_ids", "reasoning", "confidence"],
            },
        },
    }
    submit_invoice = {
        "type": "function",
        "function": {
            "name": "submit",
            "description": (
                "Final answer. Submit the invoices this payment settles, or verdict "
                "'no_match' if the reference cannot be tied to a specific invoice."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string", "enum": ["match", "no_match", "needs_human"]},
                    "invoice_ids": {"type": "array", "items": {"type": "string"}},
                    "reasoning": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["verdict", "invoice_ids", "reasoning", "confidence"],
            },
        },
    }
    if level == "bank":
        return common + [submit_bank]
    return invoice + [submit_invoice]


@dataclass
class ToolCall:
    name: str
    args: dict
    result: dict


@dataclass
class Investigation:
    """What the agent actually did, kept for the audit trail and for measurement."""

    calls: list[ToolCall] = field(default_factory=list)
    tested_combinations: list[tuple[tuple[str, ...], bool]] = field(default_factory=list)

    def record(self, call: ToolCall) -> None:
        self.calls.append(call)
        if call.name == "test_combination":
            ids = tuple(sorted(call.args.get("payment_ids", [])))
            self.tested_combinations.append((ids, bool(call.result.get("closes"))))

    def verdict_was_tested(self, payment_ids: list[str]) -> bool | None:
        """True if the agent tested exactly this set, and what its own test said."""
        key = tuple(sorted(payment_ids))
        for ids, closed in reversed(self.tested_combinations):
            if ids == key:
                return closed
        return None


class BankToolbox:
    def __init__(
        self,
        credit_paise: int,
        value_date: date,
        settlements: list[NormalisedSettlement],
        consumed: set[str],
        tolerance_paise: int = 5,
    ) -> None:
        self.credit_paise = credit_paise
        self.value_date = value_date
        self.by_id = {s.payment_id: s for s in settlements}
        self.settlements = settlements
        self.consumed = consumed
        self.tolerance = tolerance_paise

    def run(self, name: str, args: dict) -> dict:
        if name == "test_combination":
            return self.test_combination(args.get("payment_ids", []))
        if name == "get_batch":
            return self.get_batch(args.get("utr", ""))
        if name == "find_settlements":
            return self.find_settlements(
                int(args.get("days_before", 3)), args.get("min_paise"), args.get("max_paise")
            )
        return {"error": f"unknown tool {name}"}

    def test_combination(self, payment_ids: list[str]) -> dict:
        unknown = [p for p in payment_ids if p not in self.by_id]
        if unknown:
            return {"error": "unknown payment ids", "unknown": unknown}
        total = sum(self.by_id[p].net_paise for p in payment_ids)
        delta = self.credit_paise - total
        return {
            "proposed_total_paise": total,
            "bank_credit_paise": self.credit_paise,
            "delta_paise": delta,
            "closes": abs(delta) <= self.tolerance,
        }

    def get_batch(self, utr: str) -> dict:
        rows = [s for s in self.settlements if s.row.utr == utr]
        if not rows:
            return {"utr": utr, "found": 0, "settlements": []}
        return {
            "utr": utr,
            "found": len(rows),
            "batch_total_paise": sum(s.net_paise for s in rows),
            "settlements": [
                {
                    "payment_id": s.payment_id,
                    "net_paise": s.net_paise,
                    "type": s.row.type,
                    "settled_at": s.row.settled_at.isoformat(),
                    "already_attributed": s.payment_id in self.consumed,
                }
                for s in rows[:MAX_ROWS]
            ],
        }

    def find_settlements(
        self, days_before: int, min_paise: int | None, max_paise: int | None
    ) -> dict:
        earliest = self.value_date - timedelta(days=max(0, min(days_before, 30)))
        rows = [
            s
            for s in self.settlements
            if earliest <= s.row.settled_at <= self.value_date
            and s.payment_id not in self.consumed
            and (min_paise is None or s.net_paise >= min_paise)
            and (max_paise is None or s.net_paise <= max_paise)
        ]
        rows.sort(key=lambda s: (abs(s.net_paise - self.credit_paise), s.payment_id))
        return {
            "window": [earliest.isoformat(), self.value_date.isoformat()],
            "found": len(rows),
            "settlements": [
                {
                    "payment_id": s.payment_id,
                    "utr": s.row.utr,
                    "net_paise": s.net_paise,
                    "settled_at": s.row.settled_at.isoformat(),
                    "customer": s.row.customer_name,
                }
                for s in rows[:MAX_ROWS]
            ],
        }


class InvoiceToolbox:
    def __init__(self, payment: Settlement, invoices: list[Invoice]) -> None:
        self.payment = payment
        self.by_id = {i.invoice_id: i for i in invoices}
        self.invoices = invoices

    def run(self, name: str, args: dict) -> dict:
        if name == "get_invoices_for_customer":
            return self.get_invoices_for_customer(args.get("customer_name", ""))
        if name == "test_invoice_set":
            return self.test_invoice_set(args.get("invoice_ids", []))
        return {"error": f"unknown tool {name}"}

    def get_invoices_for_customer(self, customer_name: str) -> dict:
        rows = [i for i in self.invoices if i.customer_name == customer_name]
        return {
            "customer": customer_name,
            "found": len(rows),
            "invoices": [
                {
                    "invoice_id": i.invoice_id,
                    "gross_paise": i.gross_amount_paise,
                    "raised": i.invoice_date.isoformat(),
                }
                for i in rows[:MAX_ROWS]
            ],
        }

    def test_invoice_set(self, invoice_ids: list[str]) -> dict:
        unknown = [i for i in invoice_ids if i not in self.by_id]
        if unknown:
            return {"error": "unknown invoice ids", "unknown": unknown}
        cited = [self.by_id[i] for i in invoice_ids]
        wrong = [i.invoice_id for i in cited if i.customer_name != self.payment.customer_name]
        invoiced = sum(i.gross_amount_paise for i in cited)
        return {
            "payment_gross_paise": self.payment.gross_amount_paise,
            "invoiced_total_paise": invoiced,
            "customer_matches": not wrong,
            "wrong_customer": wrong,
            "payment_within_invoiced_total": self.payment.gross_amount_paise <= invoiced,
        }
