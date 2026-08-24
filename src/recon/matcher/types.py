"""Shared types for the matching pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, Field

from recon.domain.models import BankTxn, Invoice, MatchRecord, Settlement


class ReasonCode:
    """Specific reasons an item could not be resolved. 'unmatched' is not a reason."""

    AMBIGUOUS_MULTIPLE_SUBSETS = "ambiguous_multiple_subsets"
    AMBIGUOUS_MULTIPLE_BATCHES = "ambiguous_multiple_batches"
    UTR_MATCHED_AMOUNT_MISMATCH = "utr_matched_amount_mismatch"
    NO_GATEWAY_COUNTERPART = "no_gateway_counterpart"
    SUBSET_SEARCH_BUDGET_EXCEEDED = "subset_search_budget_exceeded"
    LLM_PROPOSAL_FAILED_VERIFICATION = "llm_proposal_failed_verification"
    LLM_DECLINED = "llm_declined"
    OUT_OF_SCOPE_DEBIT = "out_of_scope_debit"
    UNEXPLAINED_DEBIT = "unexplained_debit"


# Reasons where no additional context could help: the data simply does not contain a match.
UNRESOLVABLE_REASONS = frozenset({ReasonCode.NO_GATEWAY_COUNTERPART, ReasonCode.OUT_OF_SCOPE_DEBIT})

# What a human should actually do. Derived from the reason code rather than generated,
# because the action for a given failure is known and does not need inventing.
HUMAN_ACTION = {
    ReasonCode.NO_GATEWAY_COUNTERPART: (
        "No settlement record exists for this credit. Confirm with the customer whether "
        "they paid by direct transfer instead of the payment link, then post it against "
        "the invoice manually."
    ),
    ReasonCode.UTR_MATCHED_AMOUNT_MISMATCH: (
        "The UTR matches a settlement batch but the amounts differ by more than rounding. "
        "Check the gateway dashboard for payments withheld from this payout, or a refund "
        "posted after the batch closed."
    ),
    ReasonCode.AMBIGUOUS_MULTIPLE_SUBSETS: (
        "More than one combination of settlements reconciles to this credit exactly. "
        "Use the gateway's payout report for this UTR to pick the right one; do not "
        "guess from amounts alone."
    ),
    ReasonCode.AMBIGUOUS_MULTIPLE_BATCHES: (
        "Two or more settlement batches in the date window sum to this credit. "
        "Confirm the UTR with the bank before attributing it."
    ),
    ReasonCode.SUBSET_SEARCH_BUDGET_EXCEEDED: (
        "The candidate pool was too large to search exhaustively. Narrow the date window "
        "or obtain the UTR, then re-run."
    ),
    ReasonCode.LLM_PROPOSAL_FAILED_VERIFICATION: (
        "The model proposed a match that failed arithmetic verification. Its reasoning and "
        "the failing check are recorded in the evidence column. Review before accepting."
    ),
    ReasonCode.OUT_OF_SCOPE_DEBIT: (
        "An ordinary business outflow, not settlement activity. No action needed here; "
        "it belongs in the payables ledger."
    ),
    ReasonCode.UNEXPLAINED_DEBIT: (
        "A debit that is neither a reversal nor a recognised business outflow. Check the "
        "bank statement narration against the payables ledger."
    ),
    ReasonCode.LLM_DECLINED: (
        "Neither deterministic matching nor the model could tie this to a settlement. "
        "Needs manual review against the gateway dashboard."
    ),
}


class ExceptionRow(BaseModel):
    bank_txn_id: str
    value_date: date
    amount_paise: int
    reason_code: str
    closest_candidates: list[str] = Field(default_factory=list)
    what_a_human_needs_to_check: str = ""
    evidence: dict = Field(default_factory=dict)

    @property
    def resolvable_with_context(self) -> bool:
        return self.reason_code not in UNRESOLVABLE_REASONS


@dataclass
class NormalisedBank:
    txn: BankTxn
    utr: str | None
    utr_fragment: str | None

    @property
    def txn_id(self) -> str:
        return self.txn.txn_id

    @property
    def is_credit(self) -> bool:
        return self.txn.credit_paise > 0

    @property
    def amount_paise(self) -> int:
        return self.txn.credit_paise or self.txn.debit_paise


@dataclass
class NormalisedSettlement:
    row: Settlement
    net_paise: int
    net_reconstructed: bool

    @property
    def payment_id(self) -> str:
        return self.row.payment_id


@dataclass
class ReconResult:
    matches: list[MatchRecord] = field(default_factory=list)
    exceptions: list[ExceptionRow] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


@dataclass
class Sources:
    invoices: list[Invoice]
    settlements: list[Settlement]
    bank: list[BankTxn]
