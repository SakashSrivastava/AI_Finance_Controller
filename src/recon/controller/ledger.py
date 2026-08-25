"""The books.

Reconciliation answers "do these rows agree". The cash position answers "where is the
money". Neither of those is bookkeeping. A controller has to post the result to a ledger,
and that is what this module does: every bank transaction becomes a balanced journal
entry derived from the reconciliation.

Two properties make this more than a formatting exercise.

**Double entry.** Every entry balances to the paise, and so does the ledger as a whole. It
is an arithmetic invariant over the entire reconciliation, checked independently of the
matcher - if a batch were mis-attributed in a way that changed amounts, the trial balance
would not close. It is a second opinion on the same work.

**Suspense.** Anything unreconciled posts to a suspense account rather than being dropped.
Real books cannot simply omit a credit that arrived, and neither can these. The closing
suspense balance equals the value in the exception queue exactly, which ties the books
back to the reconciliation - two independent routes to the same number.

Two things deliberately stay out of suspense. A duplicate posting's original and reversal
legs post and unpost, netting to zero, because the repost carries the real entry. And an
out-of-scope debit - a salary run, a GST challan - is a known outflow rather than a
mystery, so parking it in suspense would overstate what is genuinely unreconciled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from recon.domain.models import BankTxn, MatchRecord, Settlement
from recon.matcher.types import ExceptionRow, Sources


class Account:
    BANK = "Bank"
    RECEIVABLES = "Accounts receivable"
    GATEWAY_FEES = "Gateway fees"
    GST_INPUT = "GST input credit"
    REFUNDS = "Refunds and sales returns"
    CHARGEBACKS = "Chargebacks"
    OTHER_OUTFLOWS = "Other business outflows"
    ROUNDING = "Rounding difference"
    SUSPENSE = "Suspense"


@dataclass(frozen=True)
class Line:
    account: str
    debit_paise: int = 0
    credit_paise: int = 0


@dataclass
class JournalEntry:
    ref: str
    entry_date: date
    narrative: str
    lines: list[Line] = field(default_factory=list)

    @property
    def debits(self) -> int:
        return sum(line.debit_paise for line in self.lines)

    @property
    def credits(self) -> int:
        return sum(line.credit_paise for line in self.lines)

    @property
    def balances(self) -> bool:
        return self.debits == self.credits


@dataclass
class Ledger:
    entries: list[JournalEntry] = field(default_factory=list)

    @property
    def balances(self) -> bool:
        return all(e.balances for e in self.entries) and self.total_debits == self.total_credits

    @property
    def total_debits(self) -> int:
        return sum(e.debits for e in self.entries)

    @property
    def total_credits(self) -> int:
        return sum(e.credits for e in self.entries)

    def trial_balance(self) -> dict[str, int]:
        """Net movement per account. Positive is a debit balance."""
        totals: dict[str, int] = {}
        for entry in self.entries:
            for line in entry.lines:
                totals[line.account] = (
                    totals.get(line.account, 0) + line.debit_paise - line.credit_paise
                )
        return dict(sorted(totals.items()))

    @property
    def suspense_paise(self) -> int:
        return self.trial_balance().get(Account.SUSPENSE, 0)


def _nonzero(lines: list[Line]) -> list[Line]:
    return [line for line in lines if line.debit_paise or line.credit_paise]


def build_ledger(
    sources: Sources,
    matches: list[MatchRecord],
    exceptions: list[ExceptionRow],
) -> Ledger:
    bank_by_id = {b.txn_id: b for b in sources.bank}
    settlements = {s.payment_id: s for s in sources.settlements}
    ledger = Ledger()

    matched_ids = set()
    for match in matches:
        txn = bank_by_id[match.bank_txn_id]
        matched_ids.add(match.bank_txn_id)
        if match.payment_ids:
            ledger.entries.append(
                _settlement_entry(txn, [settlements[p] for p in match.payment_ids])
            )
        elif match.tier == "tier0_out_of_scope_debit":
            # A salary run or a GST challan is a known outflow, not a mystery. Parking it
            # in suspense would overstate what is actually unreconciled.
            ledger.entries.append(
                JournalEntry(
                    ref=txn.txn_id,
                    entry_date=txn.value_date,
                    narrative="Business outflow, outside settlement scope",
                    lines=[
                        Line(Account.OTHER_OUTFLOWS, debit_paise=txn.debit_paise),
                        Line(Account.BANK, credit_paise=txn.debit_paise),
                    ],
                )
            )
        else:
            ledger.entries.append(_suspense_entry(txn, match.tier))

    for exc in exceptions:
        if exc.bank_txn_id in matched_ids:
            continue
        ledger.entries.append(_suspense_entry(bank_by_id[exc.bank_txn_id], exc.reason_code))

    ledger.entries.sort(key=lambda e: (e.entry_date, e.ref))
    return ledger


def _settlement_entry(txn: BankTxn, rows: list[Settlement]) -> JournalEntry:
    """A settled batch, posted gross with the fees the gateway withheld shown explicitly.

    The merchant never sees the fee as a payment - it is netted before the money arrives -
    so the only way it reaches the books at all is by being reconstructed here.
    """
    payments = [r for r in rows if r.type == "payment"]
    refunds = [r for r in rows if r.type == "refund"]
    chargebacks = [r for r in rows if r.type == "chargeback"]

    lines = [
        Line(Account.BANK, debit_paise=txn.credit_paise),
        Line(
            Account.GATEWAY_FEES,
            debit_paise=sum(r.fee_paise for r in payments) + sum(r.fee_paise for r in chargebacks),
        ),
        Line(
            Account.GST_INPUT,
            debit_paise=sum(r.gst_on_fee_paise for r in payments)
            + sum(r.gst_on_fee_paise for r in chargebacks),
        ),
        Line(Account.REFUNDS, debit_paise=sum(r.gross_amount_paise for r in refunds)),
        Line(Account.CHARGEBACKS, debit_paise=sum(r.gross_amount_paise for r in chargebacks)),
        Line(Account.RECEIVABLES, credit_paise=sum(r.gross_amount_paise for r in payments)),
    ]
    # The bank sometimes credits a few paise away from what the batch computes, because
    # the gateway rounds each fee independently. Double entry will not tolerate that being
    # ignored, and neither would an auditor: the difference is posted, not absorbed.
    drift = sum(l.credit_paise for l in lines) - sum(l.debit_paise for l in lines)
    if drift > 0:
        lines.append(Line(Account.ROUNDING, debit_paise=drift))
    elif drift < 0:
        lines.append(Line(Account.ROUNDING, credit_paise=-drift))

    parts = [f"{len(payments)} payment(s)"]
    if refunds:
        parts.append(f"{len(refunds)} refund(s)")
    if chargebacks:
        parts.append(f"{len(chargebacks)} chargeback(s)")
    if drift:
        parts.append(f"{abs(drift)}p rounding")
    return JournalEntry(
        ref=txn.txn_id,
        entry_date=txn.value_date,
        narrative=f"Gateway settlement: {', '.join(parts)}",
        lines=_nonzero(lines),
    )


def _suspense_entry(txn: BankTxn, reason: str) -> JournalEntry:
    """Unreconciled money still hit the bank, so it still has to be posted somewhere."""
    if txn.credit_paise:
        lines = [
            Line(Account.BANK, debit_paise=txn.credit_paise),
            Line(Account.SUSPENSE, credit_paise=txn.credit_paise),
        ]
    else:
        lines = [
            Line(Account.SUSPENSE, debit_paise=txn.debit_paise),
            Line(Account.BANK, credit_paise=txn.debit_paise),
        ]
    return JournalEntry(
        ref=txn.txn_id,
        entry_date=txn.value_date,
        narrative=f"Unreconciled - held in suspense ({reason})",
        lines=lines,
    )
