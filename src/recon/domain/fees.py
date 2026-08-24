"""Gateway fee model. Single source of truth for the generator and the matcher."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

FEE_RATE = Decimal("0.02")
GST_RATE = Decimal("0.18")
CHARGEBACK_FEE_PAISE = 50_000

TxnType = Literal["payment", "refund", "chargeback"]


@dataclass(frozen=True)
class FeeBreakdown:
    gross_paise: int
    fee_paise: int
    gst_on_fee_paise: int
    net_amount_paise: int


def _round_paise(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_fees(gross_paise: int, txn_type: TxnType = "payment") -> FeeBreakdown:
    """Fees for one gateway transaction.

    `gross_paise` is always non-negative; direction comes from `txn_type`, so an
    amount can never accidentally become a refund by carrying a minus sign.
    """
    if gross_paise < 0:
        raise ValueError("gross_paise must be non-negative; direction comes from txn_type")

    if txn_type == "payment":
        fee = _round_paise(Decimal(gross_paise) * FEE_RATE)
        gst = _round_paise(Decimal(fee) * GST_RATE)
        net = gross_paise - fee - gst
    elif txn_type == "refund":
        # The gateway returns the gross to the customer but keeps the fee it already earned.
        fee = gst = 0
        net = -gross_paise
    elif txn_type == "chargeback":
        fee = CHARGEBACK_FEE_PAISE
        gst = _round_paise(Decimal(fee) * GST_RATE)
        net = -(gross_paise + fee + gst)
    else:
        raise ValueError(f"unknown txn_type: {txn_type}")

    return FeeBreakdown(gross_paise, fee, gst, net)
