"""Tier 0: parse, normalise, reconstruct, index.

The UTR patterns here are derived from docs/CONVENTIONS.md section 5 and 6, not from the
generator's narration templates. Anything the generator emits that CONVENTIONS.md does
not describe is something this module is expected to miss, and the resulting extraction
recall is reported as a metric rather than assumed to be 100%.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from recon.domain.csvio import read_models
from recon.domain.fees import compute_fees
from recon.domain.models import BankTxn, Invoice, Settlement
from recon.matcher.types import NormalisedBank, NormalisedSettlement, Sources

# CONVENTIONS.md 5: four-letter bank code, literal N, eleven digits.
UTR_RE = re.compile(r"[A-Z]{4}N\d{11}(?!\d)")
# A narration capped mid-reference leaves a fragment. A fragment is a hint, never a key.
UTR_FRAGMENT_RE = re.compile(r"[A-Z]{4}N\d{1,10}(?!\d)")

REVERSAL_KEYWORDS = ("REV", "REVERSAL", "RETURN OF")


def load_sources(data_dir: Path) -> Sources:
    return Sources(
        invoices=read_models(data_dir / "invoices.csv", Invoice),
        settlements=read_models(data_dir / "gateway_settlements.csv", Settlement),
        bank=read_models(data_dir / "bank_statement.csv", BankTxn),
    )


def extract_utr(narration: str) -> tuple[str | None, str | None]:
    """Returns (full_utr, fragment). At most one is populated."""
    text = narration.upper()
    full = UTR_RE.search(text)
    if full:
        return full.group(0), None
    fragment = UTR_FRAGMENT_RE.search(text)
    return None, (fragment.group(0) if fragment else None)


def looks_like_reversal(narration: str) -> bool:
    text = narration.upper()
    return any(k in text for k in REVERSAL_KEYWORDS)


def effective_net(row: Settlement) -> tuple[int, bool]:
    """Net as reported, or reconstructed from gross via the fee model when blank."""
    if row.net_amount_paise is not None:
        return row.net_amount_paise, False
    return compute_fees(row.gross_amount_paise, row.type).net_amount_paise, True


def normalise_bank(rows: list[BankTxn]) -> list[NormalisedBank]:
    out = []
    for txn in rows:
        utr, fragment = extract_utr(txn.narration)
        out.append(NormalisedBank(txn=txn, utr=utr, utr_fragment=fragment))
    return out


def normalise_settlements(rows: list[Settlement]) -> list[NormalisedSettlement]:
    out = []
    for row in rows:
        net, reconstructed = effective_net(row)
        out.append(NormalisedSettlement(row=row, net_paise=net, net_reconstructed=reconstructed))
    return out


def index_by_utr(rows: list[NormalisedSettlement]) -> dict[str, list[NormalisedSettlement]]:
    index: dict[str, list[NormalisedSettlement]] = defaultdict(list)
    for row in rows:
        index[row.row.utr].append(row)
    return dict(index)


def index_by_settled_date(
    rows: list[NormalisedSettlement],
) -> dict[object, list[NormalisedSettlement]]:
    index: dict[object, list[NormalisedSettlement]] = defaultdict(list)
    for row in rows:
        index[row.row.settled_at].append(row)
    return dict(index)
