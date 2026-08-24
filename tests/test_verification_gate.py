"""The gate is the project's central claim, so it is tested against deliberate lies.

Every test here feeds the gate a verdict a model could plausibly produce - confident,
well-formed, schema-valid, and wrong - and asserts the money does not move.
"""

from datetime import date

import pytest

from recon.agent.gate import GateFailure, verify_bank_proposal, verify_invoice_proposal
from recon.agent.schemas import BankProposal, InvoiceProposal
from recon.domain.fees import compute_fees
from recon.domain.models import BankTxn, Invoice, Settlement

ACME = "Acme Traders"


def settlement(pid: str, gross: int, settled: date = date(2026, 5, 12), customer: str = ACME) -> Settlement:
    b = compute_fees(gross)
    return Settlement(
        payment_id=pid,
        invoice_ref="INV-2026-00001",
        customer_name=customer,
        captured_at=settled,
        settled_at=settled,
        utr="HDFCN00000000001",
        gross_amount_paise=gross,
        fee_paise=b.fee_paise,
        gst_on_fee_paise=b.gst_on_fee_paise,
        net_amount_paise=b.net_amount_paise,
        type="payment",
    )


@pytest.fixture
def world():
    rows = [
        settlement("pay_000001", 100_000),
        settlement("pay_000002", 200_000),
        settlement("pay_000003", 500_000, settled=date(2026, 4, 1)),  # far outside the window
    ]
    settlements = {s.payment_id: s for s in rows}
    nets = {s.payment_id: s.net_amount_paise for s in rows}
    credit = nets["pay_000001"] + nets["pay_000002"]
    bank = BankTxn(
        txn_id="bank_000001",
        value_date=date(2026, 5, 13),
        narration="NEFT-HDFCN00000000001-RAZORPAY",
        credit_paise=credit,
        balance_paise=credit,
    )
    return settlements, nets, bank


def gate(proposal, world, consumed=frozenset()):
    settlements, nets, bank = world
    return verify_bank_proposal(proposal, bank, settlements, nets, set(consumed))


def test_a_correct_proposal_is_accepted(world):
    r = gate(BankProposal(verdict="match", payment_ids=["pay_000001", "pay_000002"], confidence=0.9), world)
    assert r.accepted
    assert r.detail["delta_paise"] == 0


def test_confident_but_arithmetically_wrong_is_rejected(world):
    """The important case. The model is sure; the money does not add up; the money wins."""
    r = gate(BankProposal(verdict="match", payment_ids=["pay_000001"], reasoning="Clearly this one.", confidence=0.99), world)
    assert not r.accepted
    assert r.failure == GateFailure.SUM_MISMATCH
    assert r.detail["delta_paise"] != 0


def test_hallucinated_payment_id_is_rejected(world):
    r = gate(BankProposal(verdict="match", payment_ids=["pay_000001", "pay_999999"], confidence=0.95), world)
    assert not r.accepted
    assert r.failure == GateFailure.UNKNOWN_ID
    assert r.detail["unknown"] == ["pay_999999"]


def test_reusing_an_already_attributed_payment_is_rejected(world):
    r = gate(
        BankProposal(verdict="match", payment_ids=["pay_000001", "pay_000002"], confidence=0.9),
        world,
        consumed={"pay_000002"},
    )
    assert not r.accepted
    assert r.failure == GateFailure.ALREADY_MATCHED


def test_settlement_outside_the_date_window_is_rejected(world):
    r = gate(BankProposal(verdict="match", payment_ids=["pay_000003"], confidence=0.9), world)
    assert not r.accepted
    assert r.failure == GateFailure.OUTSIDE_WINDOW


def test_empty_match_verdict_is_rejected(world):
    r = gate(BankProposal(verdict="match", payment_ids=[], confidence=1.0), world)
    assert not r.accepted
    assert r.failure == GateFailure.EMPTY


def test_rounding_drift_inside_tolerance_is_accepted(world):
    settlements, nets, bank = world
    drifted = bank.model_copy(update={"credit_paise": bank.credit_paise + 3})
    r = verify_bank_proposal(
        BankProposal(verdict="match", payment_ids=["pay_000001", "pay_000002"], confidence=0.8),
        drifted, settlements, nets, set(),
    )
    assert r.accepted


def test_drift_beyond_tolerance_is_not_quietly_absorbed(world):
    settlements, nets, bank = world
    drifted = bank.model_copy(update={"credit_paise": bank.credit_paise + 6})
    r = verify_bank_proposal(
        BankProposal(verdict="match", payment_ids=["pay_000001", "pay_000002"], confidence=0.8),
        drifted, settlements, nets, set(),
    )
    assert not r.accepted
    assert r.failure == GateFailure.SUM_MISMATCH


def test_gate_reports_which_checks_ran():
    """Evidence, not a boolean. The exception report has to say what was checked."""
    rows = [settlement("pay_000001", 100_000)]
    bank = BankTxn(txn_id="b", value_date=date(2026, 5, 13), narration="x", credit_paise=1, balance_paise=1)
    r = verify_bank_proposal(
        BankProposal(verdict="match", payment_ids=["pay_000001"]),
        bank,
        {s.payment_id: s for s in rows},
        {s.payment_id: s.net_amount_paise for s in rows},
        set(),
    )
    assert r.checks["ids_exist"] is True
    assert r.checks["sums_to_credit"] is False


# ------------------------------------------------------------------ invoice level


def invoice(num: int, customer: str = ACME, amount: int = 100_000) -> Invoice:
    return Invoice(
        invoice_id=f"INV-2026-{num:05d}",
        customer_id="c1",
        customer_name=customer,
        invoice_date=date(2026, 5, 1),
        due_date=date(2026, 5, 31),
        gross_amount_paise=amount,
        status="paid",
    )


def test_invoice_proposal_for_another_customer_is_rejected():
    payment = settlement("pay_000001", 100_000, customer=ACME)
    invoices = {"INV-2026-01010": invoice(1010, customer="Zenith Supplies")}
    r = verify_invoice_proposal(
        InvoiceProposal(verdict="match", invoice_ids=["INV-2026-01010"], confidence=0.97),
        payment,
        invoices,
    )
    assert not r.accepted
    assert r.failure == GateFailure.WRONG_CUSTOMER


def test_payment_larger_than_everything_it_claims_to_settle_is_rejected():
    payment = settlement("pay_000001", 900_000)
    invoices = {"INV-2026-00001": invoice(1, amount=100_000)}
    r = verify_invoice_proposal(
        InvoiceProposal(verdict="match", invoice_ids=["INV-2026-00001"], confidence=0.9),
        payment,
        invoices,
    )
    assert not r.accepted
    assert r.failure == GateFailure.OVERPAID


def test_partial_payment_is_allowed_to_be_smaller_than_the_invoice():
    payment = settlement("pay_000001", 40_000)
    invoices = {"INV-2026-00001": invoice(1, amount=100_000)}
    r = verify_invoice_proposal(
        InvoiceProposal(verdict="match", invoice_ids=["INV-2026-00001"], confidence=0.9),
        payment,
        invoices,
    )
    assert r.accepted


def test_merged_payment_across_several_invoices_is_allowed():
    payment = settlement("pay_000001", 300_000)
    invoices = {
        "INV-2026-00001": invoice(1, amount=100_000),
        "INV-2026-00002": invoice(2, amount=200_000),
    }
    r = verify_invoice_proposal(
        InvoiceProposal(verdict="match", invoice_ids=["INV-2026-00001", "INV-2026-00002"], confidence=0.9),
        payment,
        invoices,
    )
    assert r.accepted


def test_hallucinated_invoice_id_is_rejected():
    payment = settlement("pay_000001", 100_000)
    r = verify_invoice_proposal(
        InvoiceProposal(verdict="match", invoice_ids=["INV-2026-99999"], confidence=1.0),
        payment,
        {"INV-2026-00001": invoice(1)},
    )
    assert not r.accepted
    assert r.failure == GateFailure.UNKNOWN_ID


def test_gate_imports_no_model_client():
    """Structural guarantee: the gate cannot be talked out of its answer.

    If the gate could reach a model, someone could eventually make it ask one.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path("src/recon/agent/gate.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any("groq" in m or "client" in m for m in imported), imported


def test_gate_rejects_a_proposal_that_is_not_uniquely_determined(world):
    """A sum that closes is not proof on its own.

    If two different subsets of the candidates both reconcile, accepting either is a coin
    flip, and the fact that one happens to match ground truth would be luck rather than
    verification. Given the pool the model was shown, the gate can tell the difference.
    """
    settlements, nets, bank = world
    # A decoy worth exactly as much as the proposed pair, so two subsets now reconcile.
    decoy_total = nets["pay_000001"] + nets["pay_000002"]
    pool = {"pay_000001": nets["pay_000001"], "pay_000002": nets["pay_000002"], "decoy": decoy_total}

    r = verify_bank_proposal(
        BankProposal(verdict="match", payment_ids=["pay_000001", "pay_000002"], confidence=0.95),
        bank, settlements, nets, set(), candidate_pool=pool,
    )
    assert not r.accepted
    assert r.failure == GateFailure.NOT_UNIQUE
    assert r.detail["subsets_that_reconcile"] >= 2


def test_uniqueness_check_passes_when_only_one_subset_reconciles(world):
    settlements, nets, bank = world
    pool = {pid: nets[pid] for pid in ("pay_000001", "pay_000002", "pay_000003")}
    r = verify_bank_proposal(
        BankProposal(verdict="match", payment_ids=["pay_000001", "pay_000002"], confidence=0.95),
        bank, settlements, nets, set(), candidate_pool=pool,
    )
    assert r.accepted
    assert r.checks["uniquely_determined"] is True
