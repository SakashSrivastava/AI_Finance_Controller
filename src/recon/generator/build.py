"""Builds the synthetic three-source dataset and its two-level ground truth.

Ground truth conventions worth stating explicitly, because the matcher is graded
against them:

* A bank credit maps to a *set* of payment ids. A payment maps to a *set* of invoice
  ids. These are different levels and are never conflated in one file.
* For a duplicate posting (credit, reversal debit, repost credit) the payment ids are
  attributed to the **repost** - the credit that survives in the closing balance. The
  original and the reversal carry empty payment sets. A matcher that asserts the same
  payments against all three rows is double counting.
* `unresolvable` rows have no gateway counterpart at all and no correct match exists.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import count
from pathlib import Path

from recon.domain.csvio import write_models
from recon.domain.fees import compute_fees
from recon.domain.models import (
    BANK_COLUMNS,
    GT_BANK_COLUMNS,
    GT_INVOICE_COLUMNS,
    INVOICE_COLUMNS,
    SETTLEMENT_COLUMNS,
    BankTxn,
    GroundTruthBank,
    GroundTruthInvoice,
    Invoice,
    Settlement,
)
from recon.generator.catalog import (
    CUSTOMER_NAMES,
    NARRATION_DIRECT_NEFT,
    NARRATION_OUT_OF_SCOPE_DEBIT,
    NARRATION_REPOST,
    NARRATION_REVERSAL,
    NARRATION_WITH_UTR,
    NARRATION_WITHOUT_UTR,
    UTR_BANK_PREFIXES,
)
from recon.generator.config import DEFAULT_CONFIG, GeneratorConfig

CHARGEBACK_OVERHEAD_PAISE = -compute_fees(0, "chargeback").net_amount_paise


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str


@dataclass
class _PendingBank:
    value_date: date
    narration: str
    credit_paise: int
    debit_paise: int
    payment_ids: list[str]
    tags: list[str]
    order: int


@dataclass
class Dataset:
    invoices: list[Invoice] = field(default_factory=list)
    settlements: list[Settlement] = field(default_factory=list)
    bank: list[BankTxn] = field(default_factory=list)
    gt_bank: list[GroundTruthBank] = field(default_factory=list)
    gt_invoice: list[GroundTruthInvoice] = field(default_factory=list)


class _Counters:
    def __init__(self) -> None:
        self.invoice = count(1)
        self.payment = count(1)
        self.utr = count(1)
        self.order = count(0)


# --------------------------------------------------------------------------- helpers


def _make_customers(rng: random.Random, cfg: GeneratorConfig) -> list[Customer]:
    names = CUSTOMER_NAMES[: cfg.n_customers]
    return [Customer(f"cust_{i:03d}", name) for i, name in enumerate(names, start=1)]


def _make_utr(rng: random.Random, counters: _Counters) -> str:
    prefix = rng.choice(UTR_BANK_PREFIXES)
    return f"{prefix}N{next(counters.utr):011d}"


def _garble(rng: random.Random, ref: str) -> str:
    ops = [
        lambda s: s.replace("I", "1", 1),
        lambda s: s.replace("0", "O", 1),
        lambda s: s.replace("-", " "),
        lambda s: s.replace("-", ""),
        lambda s: s[:-1],
        lambda s: s + "/PART",
        lambda s: s.lower(),
        lambda s: s[:4] + " " + s[4:],
        lambda s: "#" + s,
        lambda s: s.replace("5", "S", 1),
    ]
    return rng.choice(ops)(ref)


def _split_amount(rng: random.Random, total: int, n: int) -> list[int]:
    floor = 100
    if total < n * floor * 2:
        base = total // n
        parts = [base] * n
        parts[-1] += total - base * n
        return parts
    for _ in range(20):
        cuts = sorted(rng.randrange(floor, total - floor) for _ in range(n - 1))
        parts, prev = [], 0
        for c in cuts:
            parts.append(c - prev)
            prev = c
        parts.append(total - prev)
        if all(p >= floor for p in parts):
            return parts
    base = total // n
    parts = [base] * n
    parts[-1] += total - base * n
    return parts


def _make_invoice(
    rng: random.Random,
    cfg: GeneratorConfig,
    customer: Customer,
    paid_by: date,
    counters: _Counters,
    status: str = "paid",
) -> Invoice:
    invoice_date = paid_by - timedelta(days=rng.randint(0, 25))
    return Invoice(
        invoice_id=f"INV-2026-{next(counters.invoice):05d}",
        customer_id=customer.customer_id,
        customer_name=customer.name,
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=cfg.payment_terms_days),
        gross_amount_paise=rng.randint(cfg.min_invoice_paise, cfg.max_invoice_paise),
        status=status,  # type: ignore[arg-type]
    )


def _make_settlement(
    counters: _Counters,
    ref: str,
    customer: Customer,
    captured_at: date,
    settled_at: date,
    utr: str,
    gross: int,
    txn_type: str,
) -> Settlement:
    b = compute_fees(gross, txn_type)  # type: ignore[arg-type]
    return Settlement(
        payment_id=f"pay_{next(counters.payment):06d}",
        invoice_ref=ref,
        customer_name=customer.name,
        captured_at=captured_at,
        settled_at=settled_at,
        utr=utr,
        gross_amount_paise=b.gross_paise,
        fee_paise=b.fee_paise,
        gst_on_fee_paise=b.gst_on_fee_paise,
        net_amount_paise=b.net_amount_paise,
        type=txn_type,  # type: ignore[arg-type]
    )


def _make_ref(rng: random.Random, cfg: GeneratorConfig, invoice_ids: list[str]) -> tuple[str, str]:
    base = ",".join(invoice_ids)
    if rng.random() < cfg.share_garbled_ref:
        return _garble(rng, base), "garbled_ref"
    return base, "clean_ref"


def _roll_bank_tags(rng: random.Random, cfg: GeneratorConfig) -> list[str]:
    if rng.random() < cfg.share_unresolvable:
        return ["unresolvable"]
    tags: list[str] = []
    for tag, share in (
        ("timing_gap", cfg.share_timing_gap),
        ("missing_utr", cfg.share_missing_utr),
        ("refund_in_batch", cfg.share_refund_in_batch),
        ("chargeback_in_batch", cfg.share_chargeback_in_batch),
        ("duplicate_posting", cfg.share_duplicate_posting),
        ("rounding_drift", cfg.share_rounding_drift),
        ("settlement_hold", cfg.share_settlement_hold),
    ):
        if rng.random() < share:
            tags.append(tag)
    return tags or ["clean_batch"]


# ------------------------------------------------------------------ payment grouping


def _make_payment_group(
    rng: random.Random,
    cfg: GeneratorConfig,
    customer: Customer,
    captured_at: date,
    settled_at: date,
    utr: str,
    counters: _Counters,
) -> tuple[list[Invoice], list[Settlement], list[GroundTruthInvoice]]:
    roll = rng.random()
    if roll < cfg.share_merged_invoices:
        kind = "merged_invoices"
    elif roll < cfg.share_merged_invoices + cfg.share_partial_payment:
        kind = "partial_payment"
    else:
        kind = "single"

    if kind == "single":
        inv = _make_invoice(rng, cfg, customer, captured_at, counters)
        ref, ref_tag = _make_ref(rng, cfg, [inv.invoice_id])
        s = _make_settlement(
            counters, ref, customer, captured_at, settled_at, utr, inv.gross_amount_paise, "payment"
        )
        gt = GroundTruthInvoice(
            payment_id=s.payment_id, invoice_ids=[inv.invoice_id], case_tags=[ref_tag]
        )
        return [inv], [s], [gt]

    if kind == "partial_payment":
        inv = _make_invoice(rng, cfg, customer, captured_at, counters)
        parts = _split_amount(rng, inv.gross_amount_paise, rng.choice([2, 2, 3]))
        settlements, gts = [], []
        for part in parts:
            ref, ref_tag = _make_ref(rng, cfg, [inv.invoice_id])
            s = _make_settlement(
                counters, ref, customer, captured_at, settled_at, utr, part, "payment"
            )
            settlements.append(s)
            gts.append(
                GroundTruthInvoice(
                    payment_id=s.payment_id,
                    invoice_ids=[inv.invoice_id],
                    case_tags=["partial_payment", ref_tag],
                )
            )
        return [inv], settlements, gts

    invs = [
        _make_invoice(rng, cfg, customer, captured_at, counters)
        for _ in range(rng.choice([2, 2, 3]))
    ]
    ids = [i.invoice_id for i in invs]
    total = sum(i.gross_amount_paise for i in invs)
    ref, ref_tag = _make_ref(rng, cfg, ids)
    s = _make_settlement(counters, ref, customer, captured_at, settled_at, utr, total, "payment")
    gt = GroundTruthInvoice(
        payment_id=s.payment_id, invoice_ids=ids, case_tags=["merged_invoices", ref_tag]
    )
    return invs, [s], [gt]


# ------------------------------------------------------------------------- main build


def build(seed: int, cfg: GeneratorConfig = DEFAULT_CONFIG) -> Dataset:
    rng = random.Random(seed)
    counters = _Counters()
    customers = _make_customers(rng, cfg)

    ds = Dataset()
    pending: list[_PendingBank] = []
    payment_invoices: dict[str, list[str]] = {}

    for _ in range(cfg.n_bank_txns):
        tags = _roll_bank_tags(rng, cfg)
        settled_at = cfg.anchor_date - timedelta(days=rng.randint(0, cfg.window_days))

        if tags == ["unresolvable"]:
            customer = rng.choice(customers)
            narration = rng.choice(NARRATION_DIRECT_NEFT).format(
                customer=customer.name.upper(), bank=rng.choice(UTR_BANK_PREFIXES)
            )
            pending.append(
                _PendingBank(
                    value_date=settled_at,
                    narration=narration,
                    credit_paise=rng.randint(cfg.min_invoice_paise, cfg.max_invoice_paise),
                    debit_paise=0,
                    payment_ids=[],
                    tags=["unresolvable"],
                    order=next(counters.order),
                )
            )
            continue

        utr = _make_utr(rng, counters)
        captured_at = settled_at - timedelta(days=rng.randint(*cfg.settlement_lag_days))
        batch_rows: list[Settlement] = []

        for _ in range(rng.randint(cfg.min_batch_size, cfg.max_batch_size)):
            customer = rng.choice(customers)
            invs, sets_, gts = _make_payment_group(
                rng, cfg, customer, captured_at, settled_at, utr, counters
            )
            ds.invoices.extend(invs)
            ds.settlements.extend(sets_)
            ds.gt_invoice.extend(gts)
            for gt in gts:
                payment_invoices[gt.payment_id] = gt.invoice_ids
            batch_rows.extend(sets_)
        running_net = sum(s.net_amount_paise or 0 for s in batch_rows)

        anchor_payment = ds.settlements[-1]

        if "refund_in_batch" in tags:
            headroom = running_net // 2
            if headroom >= 10_000:
                gross = rng.randint(10_000, headroom)
                s = _make_settlement(
                    counters,
                    anchor_payment.invoice_ref,
                    Customer("", anchor_payment.customer_name),
                    captured_at,
                    settled_at,
                    utr,
                    gross,
                    "refund",
                )
                ds.settlements.append(s)
                batch_rows.append(s)
                running_net += s.net_amount_paise or 0
                linked = payment_invoices.get(anchor_payment.payment_id, [])
                payment_invoices[s.payment_id] = linked
                ds.gt_invoice.append(
                    GroundTruthInvoice(
                        payment_id=s.payment_id, invoice_ids=linked, case_tags=["refund"]
                    )
                )
            else:
                tags.remove("refund_in_batch")

        if "chargeback_in_batch" in tags:
            headroom = running_net - CHARGEBACK_OVERHEAD_PAISE - 10_000
            if headroom >= 10_000:
                gross = rng.randint(10_000, headroom)
                s = _make_settlement(
                    counters,
                    anchor_payment.invoice_ref,
                    Customer("", anchor_payment.customer_name),
                    captured_at,
                    settled_at,
                    utr,
                    gross,
                    "chargeback",
                )
                ds.settlements.append(s)
                batch_rows.append(s)
                running_net += s.net_amount_paise or 0
                linked = payment_invoices.get(anchor_payment.payment_id, [])
                payment_invoices[s.payment_id] = linked
                ds.gt_invoice.append(
                    GroundTruthInvoice(
                        payment_id=s.payment_id, invoice_ids=linked, case_tags=["chargeback"]
                    )
                )
            else:
                tags.remove("chargeback_in_batch")

        if "settlement_hold" in tags:
            eligible = [i for i, s in enumerate(batch_rows) if s.type == "payment"]
            if len(eligible) >= 3:
                held = set(rng.sample(eligible, rng.choice([1, 1, 2])))
                batch_rows = [s for i, s in enumerate(batch_rows) if i not in held]
                running_net = sum(s.net_amount_paise or 0 for s in batch_rows)
            else:
                tags.remove("settlement_hold")

        batch_ids = [s.payment_id for s in batch_rows]

        if not tags:
            tags = ["clean_batch"]

        value_date = settled_at
        if "timing_gap" in tags:
            value_date = settled_at + timedelta(days=rng.randint(1, 3))

        credit = running_net
        if "rounding_drift" in tags:
            credit += rng.choice([-3, -2, -1, 1, 2, 3])

        if "missing_utr" in tags:
            narration = rng.choice(NARRATION_WITHOUT_UTR)
        else:
            narration = rng.choice(NARRATION_WITH_UTR).format(utr=utr)
            if rng.random() < cfg.share_truncated_narration:
                cut = rng.randint(cfg.narration_max_chars - 5, cfg.narration_max_chars + 5)
                if len(narration) > cut:
                    narration = narration[:cut]
                    tags.append("truncated_narration")
                    # A capped narration is a perturbation, so the row is no longer clean.
                    if "clean_batch" in tags:
                        tags.remove("clean_batch")

        if "duplicate_posting" in tags:
            pending.append(
                _PendingBank(
                    value_date, narration, credit, 0, [], tags + ["dup_original"],
                    next(counters.order),
                )
            )
            rev_date = value_date + timedelta(days=1)
            pending.append(
                _PendingBank(
                    rev_date,
                    rng.choice(NARRATION_REVERSAL).format(utr=utr),
                    0,
                    credit,
                    [],
                    tags + ["dup_reversal"],
                    next(counters.order),
                )
            )
            pending.append(
                _PendingBank(
                    rev_date + timedelta(days=rng.randint(0, 1)),
                    rng.choice(NARRATION_REPOST).format(utr=utr),
                    credit,
                    0,
                    sorted(batch_ids),
                    tags + ["dup_repost"],
                    next(counters.order),
                )
            )
        else:
            pending.append(
                _PendingBank(
                    value_date, narration, credit, 0, sorted(batch_ids), tags,
                    next(counters.order),
                )
            )

    for _ in range(int(cfg.n_bank_txns * cfg.out_of_scope_debit_share)):
        customer = rng.choice(customers)
        pending.append(
            _PendingBank(
                value_date=cfg.anchor_date - timedelta(days=rng.randint(0, cfg.window_days)),
                narration=rng.choice(NARRATION_OUT_OF_SCOPE_DEBIT).format(
                    customer=customer.name.upper()
                ),
                credit_paise=0,
                debit_paise=rng.randint(cfg.min_invoice_paise, cfg.max_invoice_paise),
                payment_ids=[],
                tags=["out_of_scope_debit"],
                order=next(counters.order),
            )
        )

    n_unpaid = int(len(ds.invoices) * cfg.unpaid_invoice_share)
    for _ in range(n_unpaid):
        customer = rng.choice(customers)
        raised = cfg.anchor_date - timedelta(days=rng.randint(0, cfg.window_days))
        inv = _make_invoice(rng, cfg, customer, raised, counters, status="open")
        if inv.due_date < cfg.anchor_date:
            inv = inv.model_copy(update={"status": "overdue"})
        ds.invoices.append(inv)

    pending.sort(key=lambda p: (p.value_date, p.order))
    balance = cfg.opening_balance_paise
    for i, p in enumerate(pending, start=1):
        balance += p.credit_paise - p.debit_paise
        txn_id = f"bank_{i:06d}"
        ds.bank.append(
            BankTxn(
                txn_id=txn_id,
                value_date=p.value_date,
                narration=p.narration,
                credit_paise=p.credit_paise,
                debit_paise=p.debit_paise,
                balance_paise=balance,
            )
        )
        ds.gt_bank.append(
            GroundTruthBank(
                bank_txn_id=txn_id, payment_ids=p.payment_ids, case_tags=sorted(set(p.tags))
            )
        )

    for s in ds.settlements:
        if s.type == "payment" and rng.random() < cfg.blank_net_share:
            s.net_amount_paise = None

    ds.invoices.sort(key=lambda i: i.invoice_id)
    ds.settlements.sort(key=lambda s: s.payment_id)
    ds.gt_invoice.sort(key=lambda g: g.payment_id)
    return ds


def write_dataset(ds: Dataset, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_models(out_dir / "invoices.csv", ds.invoices, INVOICE_COLUMNS)
    write_models(out_dir / "gateway_settlements.csv", ds.settlements, SETTLEMENT_COLUMNS)
    write_models(out_dir / "bank_statement.csv", ds.bank, BANK_COLUMNS)
    write_models(out_dir / "ground_truth_bank.csv", ds.gt_bank, GT_BANK_COLUMNS)
    write_models(out_dir / "ground_truth_invoice.csv", ds.gt_invoice, GT_INVOICE_COLUMNS)
