import random

import pytest

from recon.domain.fees import CHARGEBACK_FEE_PAISE, FeeBreakdown, compute_fees
from recon.domain.money import format_paise


def test_standard_payment():
    b = compute_fees(10_000)
    assert (b.fee_paise, b.gst_on_fee_paise, b.net_amount_paise) == (200, 36, 9_764)


def test_python_round_would_be_wrong_here():
    # 2% of 25p is exactly 0.5p. Python's round() is banker's rounding and gives 0.
    assert round(0.5) == 0
    assert compute_fees(25).fee_paise == 1


def test_components_always_reconcile():
    rng = random.Random(0)
    for _ in range(2_000):
        gross = rng.randint(1, 5_000_000)
        b = compute_fees(gross)
        assert b.fee_paise + b.gst_on_fee_paise + b.net_amount_paise == gross


def test_everything_is_an_int():
    b = compute_fees(123_456)
    for v in (b.gross_paise, b.fee_paise, b.gst_on_fee_paise, b.net_amount_paise):
        assert type(v) is int


def test_refund_returns_gross_and_keeps_fee():
    assert compute_fees(100_000, "refund") == FeeBreakdown(100_000, 0, 0, -100_000)


def test_chargeback_adds_a_flat_penalty():
    b = compute_fees(100_000, "chargeback")
    assert b.fee_paise == CHARGEBACK_FEE_PAISE
    assert b.net_amount_paise == -(100_000 + CHARGEBACK_FEE_PAISE + b.gst_on_fee_paise)


def test_negative_gross_rejected():
    with pytest.raises(ValueError):
        compute_fees(-1)


@pytest.mark.parametrize(
    "paise, expected",
    [
        (0, "₹0.00"),
        (5, "₹0.05"),
        (100, "₹1.00"),
        (100_000, "₹1,000.00"),
        (12_345_678, "₹1,23,456.78"),
        (1_000_000_000, "₹1,00,00,000.00"),
        (-456_789, "-₹4,567.89"),
    ],
)
def test_indian_formatting(paise, expected):
    assert format_paise(paise) == expected
