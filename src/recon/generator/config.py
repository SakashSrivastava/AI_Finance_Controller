"""Tunable knobs for the synthetic dataset. Shares are targets, not guarantees."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class GeneratorConfig:
    n_bank_txns: int = 250
    n_customers: int = 40

    # Fixed anchor so output depends on the seed alone, never on the wall clock.
    anchor_date: date = date(2026, 6, 30)
    window_days: int = 90
    opening_balance_paise: int = 50_000_000

    min_invoice_paise: int = 50_000
    max_invoice_paise: int = 20_000_000
    min_batch_size: int = 1
    max_batch_size: int = 8
    settlement_lag_days: tuple[int, int] = (1, 2)
    payment_terms_days: int = 30

    # Share of settlement rows whose net is blank, forcing Tier 0 to reconstruct it.
    blank_net_share: float = 0.10
    # Invoices raised but never paid, so the cash position has real receivables.
    unpaid_invoice_share: float = 0.15
    # Debits that are ordinary business outflows, not settlement activity.
    out_of_scope_debit_share: float = 0.04

    # bank <-> batch case mix
    share_unresolvable: float = 0.05
    share_timing_gap: float = 0.15
    share_missing_utr: float = 0.12
    share_refund_in_batch: float = 0.06
    share_chargeback_in_batch: float = 0.04
    share_duplicate_posting: float = 0.04
    share_rounding_drift: float = 0.04
    # Payments captured under this UTR but withheld from the payout (rolling reserve,
    # risk review). The credit is then a strict SUBSET of the batch, which is the only
    # thing that makes subset search necessary rather than decorative.
    share_settlement_hold: float = 0.10
    # Share of rows arriving from an export that caps the narration field. Only
    # narrations longer than the cap actually lose data, so the observed truncation
    # rate is lower than this and depends on the template mix.
    share_truncated_narration: float = 0.25
    narration_max_chars: int = 40

    # payment <-> invoice case mix. These are per-payment-group roll probabilities, not
    # the achieved shares: a partial group emits several payment rows and a merged group
    # emits several invoices, so each tag lands on a different denominator. The achieved
    # shares are asserted against the documented targets in the consistency suite.
    share_garbled_ref: float = 0.12
    share_partial_payment: float = 0.10
    share_merged_invoices: float = 0.10


DEFAULT_CONFIG = GeneratorConfig()
