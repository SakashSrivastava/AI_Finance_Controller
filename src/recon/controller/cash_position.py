"""The cash position.

Reconciliation answers "do these rows agree". A controller has to answer "where is the
money", which is a different question built from the same evidence. Every figure here is
derived from what the matcher already produced - no new data, no model calls.

The line that matters most and that almost no reconciliation demo reports is
`under_investigation`: the rupee value currently sitting in the exception queue. A match
rate is an engineering metric; unreconciled cash is the number a finance team acts on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from recon.domain.models import Invoice, Settlement
from recon.matcher.invoices import InvoiceMatch
from recon.matcher.types import ExceptionRow, Sources
from recon.domain.models import MatchRecord

AGEING_BUCKETS = ((0, 30), (31, 60), (61, 10_000))
# CONVENTIONS.md 3: a payout reaches the bank within this many days of settling.
SETTLEMENT_LAG_DAYS = 3


@dataclass
class Bucket:
    count: int = 0
    paise: int = 0

    def add(self, amount: int) -> None:
        self.count += 1
        self.paise += amount


@dataclass
class CashPosition:
    as_of: date
    settled: Bucket = field(default_factory=Bucket)
    in_flight: Bucket = field(default_factory=Bucket)
    settled_but_unattributed: Bucket = field(default_factory=Bucket)
    under_investigation: Bucket = field(default_factory=Bucket)
    unresolvable: Bucket = field(default_factory=Bucket)
    overdue: dict[str, Bucket] = field(default_factory=dict)
    not_yet_due: Bucket = field(default_factory=Bucket)
    fees_paise: int = 0
    gst_paise: int = 0

    @property
    def total_receivables_paise(self) -> int:
        return sum(b.paise for b in self.overdue.values()) + self.not_yet_due.paise


def build_cash_position(
    sources: Sources,
    matches: list[MatchRecord],
    exceptions: list[ExceptionRow],
    invoice_matches: list[InvoiceMatch],
) -> CashPosition:
    as_of = max(b.value_date for b in sources.bank)
    position = CashPosition(as_of=as_of)
    position.overdue = {f"{lo}-{hi}" if hi < 10_000 else f"{lo}+": Bucket() for lo, hi in AGEING_BUCKETS}

    bank_by_id = {b.txn_id: b for b in sources.bank}
    attributed: set[str] = set()
    for m in matches:
        attributed.update(m.payment_ids)
        if m.payment_ids:
            position.settled.add(bank_by_id[m.bank_txn_id].credit_paise)

    # A payment with no bank attribution is one of two very different things, and
    # conflating them overstates incoming cash. If it settled inside the final
    # settlement-lag window it is genuinely still in transit. If it settled earlier, the
    # money has already moved and what is missing is the attribution, not the cash - that
    # belongs with the exception queue, not with expected receipts.
    in_transit_from = as_of - timedelta(days=SETTLEMENT_LAG_DAYS)
    for row in sources.settlements:
        if row.payment_id in attributed or row.type != "payment":
            continue
        if row.settled_at >= in_transit_from:
            position.in_flight.add(_net(row))
        else:
            position.settled_but_unattributed.add(_net(row))

    for exc in exceptions:
        target = position.unresolvable if not exc.resolvable_with_context else position.under_investigation
        target.add(exc.amount_paise)

    settled_invoices = {i for m in invoice_matches for i in m.invoice_ids}
    for invoice in sources.invoices:
        if invoice.invoice_id in settled_invoices:
            continue
        if invoice.due_date >= as_of:
            position.not_yet_due.add(invoice.gross_amount_paise)
            continue
        age = (as_of - invoice.due_date).days
        for lo, hi in AGEING_BUCKETS:
            if lo <= age <= hi:
                key = f"{lo}-{hi}" if hi < 10_000 else f"{lo}+"
                position.overdue[key].add(invoice.gross_amount_paise)
                break

    position.fees_paise = sum(s.fee_paise for s in sources.settlements)
    position.gst_paise = sum(s.gst_on_fee_paise for s in sources.settlements)
    return position


def _net(row: Settlement) -> int:
    from recon.domain.fees import compute_fees

    if row.net_amount_paise is not None:
        return row.net_amount_paise
    return compute_fees(row.gross_amount_paise, row.type).net_amount_paise
