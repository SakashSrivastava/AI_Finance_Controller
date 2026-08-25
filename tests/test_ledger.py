"""The books, and the invariants that make them a second opinion rather than a rendering.

Double entry is an arithmetic check over the whole reconciliation that does not consult
the matcher's own logic. If a batch were mis-attributed in a way that moved amounts, the
trial balance would stop closing.
"""

from pathlib import Path

import pytest

from recon.controller.ledger import Account, build_ledger
from recon.pipeline import run_pipeline

DATA = Path("data/7")


@pytest.fixture(scope="module")
def result():
    return run_pipeline(DATA, use_llm=False)


@pytest.fixture(scope="module")
def ledger(result):
    return build_ledger(result.sources, result.bank.matches, result.bank.exceptions)


def test_every_journal_entry_balances(ledger):
    unbalanced = [(e.ref, e.debits - e.credits) for e in ledger.entries if not e.balances]
    assert not unbalanced, f"entries out of balance: {unbalanced[:5]}"


def test_the_ledger_as_a_whole_balances(ledger):
    assert ledger.total_debits == ledger.total_credits
    assert ledger.balances


def test_every_bank_row_is_posted(ledger, result):
    """Books cannot silently omit money that arrived."""
    assert {e.ref for e in ledger.entries} == {b.txn_id for b in result.sources.bank}


def test_suspense_equals_the_exception_queue(ledger, result):
    """Two independent routes to the same number.

    The exception queue is produced by the matcher. The suspense balance falls out of
    double-entry bookkeeping over every bank row. They must agree to the paise, and if
    they ever stop agreeing then one of the two is wrong.
    """
    queue = sum(e.amount_paise for e in result.bank.exceptions)
    assert -ledger.suspense_paise == queue


def test_rounding_drift_is_posted_not_absorbed(ledger):
    """The gateway rounds each fee independently, so a batch can miss the credit by a few
    paise. Double entry will not tolerate that being ignored."""
    trial = ledger.trial_balance()
    assert Account.ROUNDING in trial, "no rounding differences were posted at all"
    assert abs(trial[Account.ROUNDING]) < 100, "rounding difference should be paise, not rupees"


def test_out_of_scope_debits_do_not_inflate_suspense(ledger):
    """A salary run is a known outflow. Parking it in suspense would overstate what is
    genuinely unreconciled."""
    trial = ledger.trial_balance()
    assert trial.get(Account.OTHER_OUTFLOWS, 0) > 0


def test_duplicate_posting_legs_net_to_zero(result):
    """A credit, its reversal and the repost are one event. The first two must cancel."""
    ledger = build_ledger(result.sources, result.bank.matches, result.bank.exceptions)
    dup_refs = {
        m.bank_txn_id
        for m in result.bank.matches
        if m.tier in ("tier0_dup_original", "tier0_dup_reversal")
    }
    assert dup_refs, "no duplicate postings in this dataset"
    movement = 0
    for entry in ledger.entries:
        if entry.ref in dup_refs:
            for line in entry.lines:
                if line.account == Account.BANK:
                    movement += line.debit_paise - line.credit_paise
    assert movement == 0, "duplicate posting legs left a net bank movement"


def test_fees_reach_the_books_at_all(ledger):
    """The merchant never sees the fee as a payment - it is netted before the money
    arrives - so reconstructing it here is the only way it is ever recorded."""
    trial = ledger.trial_balance()
    assert trial[Account.GATEWAY_FEES] > 0
    assert trial[Account.GST_INPUT] > 0


def test_receivables_are_credited_gross_not_net(ledger):
    """Posting net would understate revenue by the fee and lose the GST input credit.

    Scoped to settlement entries: the bank account also carries unreconciled credits that
    have no receivable behind them, so the ledger-wide totals are not comparable.
    """
    receivables = bank = 0
    for entry in ledger.entries:
        accounts = {line.account for line in entry.lines}
        if Account.RECEIVABLES not in accounts:
            continue
        for line in entry.lines:
            if line.account == Account.RECEIVABLES:
                receivables += line.credit_paise
            elif line.account == Account.BANK:
                bank += line.debit_paise
    assert receivables > bank, "receivables should exceed cash received by the fees withheld"
    assert receivables - bank > 1_000_000, "the gap should be the fees, which are material"


def test_ledger_is_deterministic(result):
    a = build_ledger(result.sources, result.bank.matches, result.bank.exceptions)
    b = build_ledger(result.sources, result.bank.matches, result.bank.exceptions)
    assert [(e.ref, e.debits, e.credits) for e in a.entries] == [
        (e.ref, e.debits, e.credits) for e in b.entries
    ]
