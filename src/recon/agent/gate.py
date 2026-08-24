"""The verification gate.

Every match the model proposes is re-derived here from the source data before it is
allowed to become an assertion about money. The gate never calls a model, imports no
client, and is a pure function of (proposal, sources) - which is why it can be tested
exhaustively against deliberately wrong verdicts.

A proposal that fails any check is not repaired, retried, or downgraded to a weaker
match. It is recorded as `llm_proposal_failed_verification` and handed to a human. The
count of these is the project's headline diagnostic, because it measures the thing the
track says is the real bottleneck: not whether a model can generate a plausible answer,
but whether anything can tell if it is right.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from recon.domain.models import BankTxn, Invoice, Settlement
from recon.agent.schemas import BankProposal, InvoiceProposal


class GateFailure:
    EMPTY = "empty_payment_set"
    UNKNOWN_ID = "cited_id_does_not_exist"
    ALREADY_MATCHED = "cited_payment_already_attributed"
    OUTSIDE_WINDOW = "settlement_outside_date_window"
    SUM_MISMATCH = "amounts_do_not_sum_to_the_credit"
    WRONG_CUSTOMER = "invoice_belongs_to_another_customer"
    OVERPAID = "payment_exceeds_invoiced_total"


@dataclass
class GateResult:
    accepted: bool
    failure: str | None = None
    checks: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)


def verify_bank_proposal(
    proposal: BankProposal,
    bank_txn: BankTxn,
    settlements: dict[str, Settlement],
    nets: dict[str, int],
    consumed: set[str],
    window_days: int = 3,
    tolerance_paise: int = 5,
) -> GateResult:
    """Re-derive the arithmetic. The model's confidence is not evidence."""
    ids = list(proposal.payment_ids)
    checks: dict[str, bool] = {}

    checks["non_empty"] = bool(ids)
    if not checks["non_empty"]:
        return GateResult(False, GateFailure.EMPTY, checks)

    unknown = [pid for pid in ids if pid not in settlements]
    checks["ids_exist"] = not unknown
    if unknown:
        return GateResult(False, GateFailure.UNKNOWN_ID, checks, {"unknown": unknown})

    clash = sorted(set(ids) & consumed)
    checks["not_already_attributed"] = not clash
    if clash:
        return GateResult(False, GateFailure.ALREADY_MATCHED, checks, {"already_matched": clash})

    latest = bank_txn.value_date
    earliest = latest - timedelta(days=window_days)
    outside = [
        pid for pid in ids if not (earliest <= settlements[pid].settled_at <= latest)
    ]
    checks["inside_date_window"] = not outside
    if outside:
        return GateResult(
            False,
            GateFailure.OUTSIDE_WINDOW,
            checks,
            {"outside": outside, "window": [earliest.isoformat(), latest.isoformat()]},
        )

    total = sum(nets[pid] for pid in ids)
    delta = bank_txn.credit_paise - total
    checks["sums_to_credit"] = abs(delta) <= tolerance_paise
    detail = {
        "proposed_total_paise": total,
        "credit_paise": bank_txn.credit_paise,
        "delta_paise": delta,
        "tolerance_paise": tolerance_paise,
    }
    if not checks["sums_to_credit"]:
        return GateResult(False, GateFailure.SUM_MISMATCH, checks, detail)

    return GateResult(True, None, checks, detail)


def verify_invoice_proposal(
    proposal: InvoiceProposal,
    payment: Settlement,
    invoices: dict[str, Invoice],
) -> GateResult:
    """The invoice level has arithmetic too: you cannot pay more than was invoiced."""
    ids = list(proposal.invoice_ids)
    checks: dict[str, bool] = {}

    checks["non_empty"] = bool(ids)
    if not checks["non_empty"]:
        return GateResult(False, GateFailure.EMPTY, checks)

    unknown = [i for i in ids if i not in invoices]
    checks["ids_exist"] = not unknown
    if unknown:
        return GateResult(False, GateFailure.UNKNOWN_ID, checks, {"unknown": unknown})

    cited = [invoices[i] for i in ids]
    wrong = [i.invoice_id for i in cited if i.customer_name != payment.customer_name]
    checks["customer_corroborates"] = not wrong
    if wrong:
        return GateResult(
            False,
            GateFailure.WRONG_CUSTOMER,
            checks,
            {"payment_customer": payment.customer_name, "mismatched": wrong},
        )

    invoiced = sum(i.gross_amount_paise for i in cited)
    checks["within_invoiced_total"] = payment.gross_amount_paise <= invoiced
    detail = {"payment_gross_paise": payment.gross_amount_paise, "invoiced_total_paise": invoiced}
    if not checks["within_invoiced_total"]:
        return GateResult(False, GateFailure.OVERPAID, checks, detail)

    return GateResult(True, None, checks, detail)
