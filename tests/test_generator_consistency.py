"""The generator's correctness proof.

Every metric this project reports is downstream of the ground truth being right, and a
subtly wrong ground truth is a lie you cannot see. These assertions are the only thing
standing between "measured 96% precision" and "measured nothing".
"""

from __future__ import annotations

import filecmp
from collections import Counter, defaultdict

import pytest

from recon.domain.fees import compute_fees
from recon.domain.models import Settlement
from recon.generator.build import build, write_dataset
from recon.generator.config import DEFAULT_CONFIG

CFG = DEFAULT_CONFIG
# Rows that exist only as artifacts of one duplicate-posting event.
DUP_ECHOES = {"dup_reversal", "dup_repost"}


@pytest.fixture(scope="module")
def ds():
    return build(42)


def effective_net(s: Settlement) -> int:
    """Net as the matcher will see it: reconstructed from gross when the field is blank."""
    if s.net_amount_paise is not None:
        return s.net_amount_paise
    return compute_fees(s.gross_amount_paise, s.type).net_amount_paise


def test_fee_components_recompute(ds):
    for s in ds.settlements:
        b = compute_fees(s.gross_amount_paise, s.type)
        assert s.fee_paise == b.fee_paise
        assert s.gst_on_fee_paise == b.gst_on_fee_paise
        assert effective_net(s) == b.net_amount_paise


def test_batches_sum_exactly_to_their_bank_credit(ds):
    nets = {s.payment_id: effective_net(s) for s in ds.settlements}
    bank = {b.txn_id: b for b in ds.bank}
    checked = 0
    for gt in ds.gt_bank:
        if not gt.payment_ids or "rounding_drift" in gt.case_tags:
            continue
        total = sum(nets[p] for p in gt.payment_ids)
        assert total == bank[gt.bank_txn_id].credit_paise, gt.bank_txn_id
        checked += 1
    assert checked > 100


def test_rounding_drift_is_small_and_real(ds):
    nets = {s.payment_id: effective_net(s) for s in ds.settlements}
    bank = {b.txn_id: b for b in ds.bank}
    drifts = [
        abs(sum(nets[p] for p in gt.payment_ids) - bank[gt.bank_txn_id].credit_paise)
        for gt in ds.gt_bank
        if gt.payment_ids and "rounding_drift" in gt.case_tags
    ]
    assert drifts, "no rounding_drift rows generated"
    assert all(1 <= d <= 3 for d in drifts)


def test_ground_truth_ids_all_exist(ds):
    payments = {s.payment_id for s in ds.settlements}
    invoices = {i.invoice_id for i in ds.invoices}
    for gt in ds.gt_bank:
        assert set(gt.payment_ids) <= payments
    for gt in ds.gt_invoice:
        assert gt.payment_id in payments
        assert set(gt.invoice_ids) <= invoices


def test_every_payment_is_attributed_exactly_once(ds):
    seen = Counter(p for gt in ds.gt_bank for p in gt.payment_ids)
    assert not [p for p, n in seen.items() if n > 1], "payment claimed by two bank rows"
    assert set(seen) == {s.payment_id for s in ds.settlements}, "payment lost from ground truth"


def test_unresolvable_rows_have_no_counterpart(ds):
    rows = [gt for gt in ds.gt_bank if "unresolvable" in gt.case_tags]
    assert rows, "no unresolvable rows generated"
    assert all(gt.payment_ids == [] for gt in rows)


def test_duplicate_postings_attribute_to_the_repost_only(ds):
    by_tag = {t: [gt for gt in ds.gt_bank if t in gt.case_tags] for t in DUP_ECHOES | {"dup_original"}}
    assert by_tag["dup_original"], "no duplicate_posting rows generated"
    assert len(by_tag["dup_original"]) == len(by_tag["dup_reversal"]) == len(by_tag["dup_repost"])
    assert all(gt.payment_ids == [] for gt in by_tag["dup_original"])
    assert all(gt.payment_ids == [] for gt in by_tag["dup_reversal"])
    assert all(gt.payment_ids for gt in by_tag["dup_repost"])


def test_running_balance_is_consistent(ds):
    balance = CFG.opening_balance_paise
    for txn in ds.bank:
        balance += txn.credit_paise - txn.debit_paise
        assert txn.balance_paise == balance, txn.txn_id


def test_bank_rows_are_in_date_order(ds):
    dates = [b.value_date for b in ds.bank]
    assert dates == sorted(dates)


@pytest.mark.parametrize(
    "tag, target",
    [
        ("unresolvable", CFG.share_unresolvable),
        ("timing_gap", CFG.share_timing_gap),
        ("missing_utr", CFG.share_missing_utr),
        ("refund_in_batch", CFG.share_refund_in_batch),
        ("chargeback_in_batch", CFG.share_chargeback_in_batch),
        ("duplicate_posting", CFG.share_duplicate_posting),
        ("rounding_drift", CFG.share_rounding_drift),
    ],
)
def test_bank_case_mix_is_near_target(ds, tag, target):
    # One duplicate-posting event spans three rows; count the event, not the echoes.
    slots = [
        gt
        for gt in ds.gt_bank
        if not (DUP_ECHOES & set(gt.case_tags)) and "out_of_scope_debit" not in gt.case_tags
    ]
    share = sum(tag in gt.case_tags for gt in slots) / len(slots)
    assert abs(share - target) < 0.05, f"{tag}: {share:.3f} vs target {target}"


def _payment_rows(ds):
    return [gt for gt in ds.gt_invoice if not ({"refund", "chargeback"} & set(gt.case_tags))]


def test_partial_payment_share(ds):
    """'One invoice settled across two or more payments' - an invoice-level property."""
    paid_by = defaultdict(set)
    for gt in _payment_rows(ds):
        for invoice_id in gt.invoice_ids:
            paid_by[invoice_id].add(gt.payment_id)
    share = sum(len(v) >= 2 for v in paid_by.values()) / len(paid_by)
    assert abs(share - 0.10) < 0.035, f"partial_payment: {share:.3f}"


def test_merged_invoice_share(ds):
    """'One payment covers two or more invoices' - a payment-level property."""
    rows = _payment_rows(ds)
    share = sum(len(gt.invoice_ids) >= 2 for gt in rows) / len(rows)
    assert abs(share - 0.08) < 0.035, f"merged_invoices: {share:.3f}"


def test_garbled_ref_share(ds):
    rows = _payment_rows(ds)
    share = sum("garbled_ref" in gt.case_tags for gt in rows) / len(rows)
    assert abs(share - 0.12) < 0.035, f"garbled_ref: {share:.3f}"


def test_some_nets_are_blank_so_tier0_has_work(ds):
    blank = sum(s.net_amount_paise is None for s in ds.settlements)
    assert 0.05 < blank / len(ds.settlements) < 0.15


def test_same_seed_is_byte_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write_dataset(build(42), a)
    write_dataset(build(42), b)
    for name in (
        "invoices.csv",
        "gateway_settlements.csv",
        "bank_statement.csv",
        "ground_truth_bank.csv",
        "ground_truth_invoice.csv",
    ):
        assert filecmp.cmp(a / name, b / name, shallow=False), name


def test_different_seeds_differ(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write_dataset(build(42), a)
    write_dataset(build(7), b)
    assert not filecmp.cmp(a / "bank_statement.csv", b / "bank_statement.csv", shallow=False)
