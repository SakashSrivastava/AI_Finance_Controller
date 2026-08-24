from datetime import date

import pytest

from recon.domain.fees import compute_fees
from recon.domain.models import Invoice, Settlement
from recon.matcher.invoices import InvoiceMatcher, canonical, split_refs

ACME = "Acme Traders"
OTHER = "Zenith Supplies"


def invoice(num: int, customer: str = ACME, amount: int = 100_000) -> Invoice:
    return Invoice(
        invoice_id=f"INV-2026-{num:05d}",
        customer_id="cust_001" if customer == ACME else "cust_002",
        customer_name=customer,
        invoice_date=date(2026, 5, 1),
        due_date=date(2026, 5, 31),
        gross_amount_paise=amount,
        status="paid",
    )


def payment(ref: str, customer: str = ACME, amount: int = 100_000, pid: str = "pay_000001") -> Settlement:
    b = compute_fees(amount)
    return Settlement(
        payment_id=pid,
        invoice_ref=ref,
        customer_name=customer,
        captured_at=date(2026, 5, 10),
        settled_at=date(2026, 5, 12),
        utr="HDFCN00000000001",
        gross_amount_paise=amount,
        fee_paise=b.fee_paise,
        gst_on_fee_paise=b.gst_on_fee_paise,
        net_amount_paise=b.net_amount_paise,
        type="payment",
    )


def run(invoices, settlements):
    return InvoiceMatcher(invoices, settlements).run()


def test_canonical_folds_case_separators_and_confusable_glyphs():
    base = canonical("INV-2026-00110")
    assert canonical("inv 2026 00110") == base
    assert canonical("#INV-2026-OO11O") == base
    assert canonical("1NV202600110") == base


def test_split_refs_handles_lists_and_trailing_annotations():
    assert split_refs("INV-2026-00001,INV-2026-00002") == ["INV-2026-00001", "INV-2026-00002"]
    assert split_refs("INV-2026-00001/PART") == ["INV-2026-00001"]


def test_exact_reference_matches():
    matches, residue = run([invoice(110)], [payment("INV-2026-00110")])
    assert not residue
    assert matches[0].invoice_ids == ["INV-2026-00110"]
    assert matches[0].tier == "inv1_exact_ref"


def test_garbled_reference_matches_after_folding():
    matches, _ = run([invoice(110)], [payment("inv 2026 OO11O")])
    assert matches[0].invoice_ids == ["INV-2026-00110"]
    assert matches[0].tier == "inv2_canonical_ref"


def test_reference_buried_in_free_text_is_extracted():
    matches, _ = run([invoice(745)], [payment("PAYMENT FOR INV-2026-00745")])
    assert matches[0].invoice_ids == ["INV-2026-00745"]
    assert matches[0].tier == "inv3_embedded_id"


def test_one_payment_covering_several_invoices():
    invoices = [invoice(1), invoice(2)]
    matches, _ = run(invoices, [payment("INV-2026-00001,INV-2026-00002", amount=200_000)])
    assert sorted(matches[0].invoice_ids) == ["INV-2026-00001", "INV-2026-00002"]


def test_partial_payments_both_point_at_the_same_invoice():
    inv = invoice(50, amount=100_000)
    settlements = [
        payment("INV-2026-00050", amount=40_000, pid="pay_000001"),
        payment("INV-2026-00050", amount=60_000, pid="pay_000002"),
    ]
    matches, residue = run([inv], settlements)
    assert not residue
    assert all(m.invoice_ids == ["INV-2026-00050"] for m in matches)


def test_transposed_digits_that_form_a_real_invoice_are_not_accepted():
    """The finding this whole project is about, in miniature.

    Transposing two digits of INV-2026-00110 yields INV-2026-01010, which *exists* and
    belongs to a different customer. Exact string matching does not fail here - it
    succeeds, confidently, on the wrong invoice. Only corroborating the customer catches
    it, which is the same rule that makes the LLM verification gate necessary later.
    """
    invoices = [invoice(110, ACME, 100_000), invoice(1010, OTHER, 777_000)]
    matches, residue = run(invoices, [payment("INV-2026-01010", customer=ACME, amount=100_000)])
    assert matches, "should recover via amount and customer rather than give up"
    assert matches[0].invoice_ids == ["INV-2026-00110"]
    assert matches[0].tier != "inv1_exact_ref", "must not be accepted at exact-match confidence"
    assert matches[0].confidence < 1.0


def test_a_reference_for_another_customer_never_resolves_silently():
    invoices = [invoice(1010, OTHER, 777_000)]
    matches, residue = run(invoices, [payment("INV-2026-01010", customer=ACME, amount=100_000)])
    assert not matches
    assert residue[0].payment_id == "pay_000001"


def test_ambiguous_amount_is_left_as_residue_rather_than_guessed():
    invoices = [invoice(200, ACME, 100_000), invoice(201, ACME, 100_000)]
    matches, residue = run(invoices, [payment("TOTALLY UNPARSEABLE", amount=100_000)])
    assert not matches
    assert residue


def test_every_cited_reference_must_resolve():
    """Half a merged payment is not a match: the money would not tie out."""
    invoices = [invoice(1)]
    matches, residue = run(invoices, [payment("INV-2026-00001,INV-2026-09999", amount=200_000)])
    assert not matches
    assert residue
