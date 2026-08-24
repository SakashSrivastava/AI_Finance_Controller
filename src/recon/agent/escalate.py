"""Escalation of the deterministic residue to a language model.

The division of labour is deliberate. Code keeps arithmetic, because code is strictly
better at summing subsets. The model gets semantics - reading a mangled reference,
judging whether "00423" means INV-2026-00423 - because that is where it beats a regex
and a fuzzy ratio.

Every proposal, on either level, goes through the gate before it becomes an assertion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from recon.agent.client import DEFAULT_MODEL, CachedLLM, ModelCallFailed
from recon.agent.gate import GateResult, verify_bank_proposal, verify_invoice_proposal
from recon.agent.schemas import BANK_SCHEMA, INVOICE_SCHEMA, BankProposal, InvoiceProposal
from recon.domain.models import Invoice, Settlement
from recon.matcher.invoices import InvoiceResidue
from recon.matcher.types import ExceptionRow, NormalisedSettlement

MAX_CANDIDATES = 15

BANK_SYSTEM = """You reconcile an Indian merchant's bank statement against payment gateway settlements.

How the money works:
- The gateway batches many payments settling on the same day and pays out ONE net amount.
  A bank credit therefore equals the SUM of several settlements, never a single payment.
- Each payment nets gross minus a 2% fee minus 18% GST on that fee.
- Refunds and chargebacks carry negative net and reduce the payout.
- The bank value date may lag the settlement date by up to 3 days.
- Some payments captured under a batch are withheld from the payout (rolling reserve or
  risk review), so a credit may correspond to a SUBSET of a batch.
- Some credits are customers paying the merchant directly, bypassing the gateway. These
  have NO settlement counterpart and the correct answer is no_match.

Deterministic code has already tried exact UTR matching, whole-batch sums, and bounded
subset search, and failed. Do not repeat arithmetic it has already done exhaustively.
Judge whether the narration and context point to a specific set of settlements.

Answer no_match when nothing fits. A wrong match on money is far worse than no match."""

INVOICE_SYSTEM = """You resolve mangled invoice references on an Indian merchant's payments.

The reference is transcribed by the customer, so it arrives corrupted: transposed digits,
missing prefixes (a bare "00423" meaning INV-2026-00423), the word INVOICE instead of INV,
truncation, character confusion between I/1, O/0 and S/5, or free text wrapped around it.

Rules:
- A payment may settle one invoice, part of one invoice (paying less than the full
  amount is normal), or several invoices at once.
- Every invoice you cite must belong to the paying customer.
- A payment can never exceed the total of the invoices it settles.
- Deterministic matching already tried exact, case-and-separator-folded, embedded-token
  and fuzzy lookups. They failed or were ambiguous.

Answer no_match if the reference cannot be tied to a specific invoice with confidence."""


@dataclass
class Outcome:
    target_id: str
    level: str
    model: str
    verdict: str
    proposed: list[str]
    reasoning: str
    confidence: float
    accepted: bool
    failure: str | None = None
    checks: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)


def _rupees(paise: int) -> str:
    return f"{paise/100:,.2f}"


def build_bank_packet(exception: ExceptionRow, narration: str, candidates: list[NormalisedSettlement], window_days: int) -> str:
    earliest = exception.value_date - timedelta(days=window_days)
    lines = [
        "UNMATCHED BANK CREDIT",
        f"  id          {exception.bank_txn_id}",
        f"  value_date  {exception.value_date}",
        f"  amount      {exception.amount_paise} paise (Rs {_rupees(exception.amount_paise)})",
        f"  narration   {narration!r}",
        "",
        f"DETERMINISTIC TIERS FAILED: {exception.reason_code}",
        "",
        f"UNMATCHED SETTLEMENTS SETTLING {earliest} to {exception.value_date}:",
    ]
    if not candidates:
        lines.append("  (none)")
    for s in candidates:
        lines.append(
            f"  {s.payment_id}  utr={s.row.utr}  settled={s.row.settled_at}  "
            f"net={s.net_paise}  customer={s.row.customer_name}"
        )
    lines += [
        "",
        "Which settlements, if any, make up this credit? Their net amounts must sum to it.",
    ]
    return "\n".join(lines)


def build_invoice_packet(residue: InvoiceResidue, invoices: dict[str, Invoice]) -> str:
    lines = [
        "PAYMENT WITH AN UNRESOLVED INVOICE REFERENCE",
        f"  payment_id  {residue.payment_id}",
        f"  customer    {residue.customer_name}",
        f"  gross       {residue.gross_amount_paise} paise (Rs {_rupees(residue.gross_amount_paise)})",
        f"  reference   {residue.raw_ref!r}   <- as received, corrupted",
        "",
        f"INVOICES FOR {residue.customer_name}:",
    ]
    for invoice_id in residue.candidates:
        inv = invoices.get(invoice_id)
        if inv:
            lines.append(
                f"  {inv.invoice_id}  raised={inv.invoice_date}  gross={inv.gross_amount_paise}"
            )
    lines += ["", "Which invoice or invoices does this payment settle?"]
    return "\n".join(lines)


class Escalator:
    def __init__(self, llm: CachedLLM, model: str = DEFAULT_MODEL, window_days: int = 3, tolerance_paise: int = 5):
        self.llm = llm
        self.model = model
        self.window_days = window_days
        self.tolerance_paise = tolerance_paise
        self.outcomes: list[Outcome] = []

    # ------------------------------------------------------------- bank level

    def escalate_bank(
        self,
        exceptions: list[ExceptionRow],
        narrations: dict[str, str],
        settlements: dict[str, Settlement],
        nets: dict[str, int],
        available: list[NormalisedSettlement],
        consumed: set[str],
        bank_rows: dict,
    ) -> list[Outcome]:
        for exc in exceptions:
            candidates = self._bank_candidates(exc, available)
            packet = build_bank_packet(exc, narrations.get(exc.bank_txn_id, ""), candidates, self.window_days)
            try:
                raw = self.llm.propose(BANK_SYSTEM, packet, BANK_SCHEMA, self.model)
            except ModelCallFailed as exc_err:
                self.outcomes.append(self._call_failed(exc.bank_txn_id, "bank", str(exc_err)))
                continue
            proposal = BankProposal.model_validate(raw)

            if proposal.verdict != "match":
                self.outcomes.append(self._declined(exc.bank_txn_id, "bank", proposal))
                continue

            gate = verify_bank_proposal(
                proposal,
                bank_rows[exc.bank_txn_id],
                settlements,
                nets,
                consumed,
                self.window_days,
                self.tolerance_paise,
            )
            self.outcomes.append(self._graded(exc.bank_txn_id, "bank", proposal, proposal.payment_ids, gate))
        return self.outcomes

    def _bank_candidates(self, exc: ExceptionRow, available: list[NormalisedSettlement]) -> list[NormalisedSettlement]:
        earliest = exc.value_date - timedelta(days=self.window_days)
        pool = [s for s in available if earliest <= s.row.settled_at <= exc.value_date]
        pool.sort(key=lambda s: (abs(s.net_paise - exc.amount_paise), s.payment_id))
        return pool[:MAX_CANDIDATES]

    # ---------------------------------------------------------- invoice level

    def escalate_invoices(
        self, residue: list[InvoiceResidue], payments: dict[str, Settlement], invoices: dict[str, Invoice]
    ) -> list[Outcome]:
        for item in residue:
            packet = build_invoice_packet(item, invoices)
            try:
                raw = self.llm.propose(INVOICE_SYSTEM, packet, INVOICE_SCHEMA, self.model)
            except ModelCallFailed as exc_err:
                self.outcomes.append(self._call_failed(item.payment_id, "invoice", str(exc_err)))
                continue
            proposal = InvoiceProposal.model_validate(raw)

            if proposal.verdict != "match":
                self.outcomes.append(self._declined(item.payment_id, "invoice", proposal))
                continue

            gate = verify_invoice_proposal(proposal, payments[item.payment_id], invoices)
            self.outcomes.append(
                self._graded(item.payment_id, "invoice", proposal, proposal.invoice_ids, gate)
            )
        return self.outcomes

    # ----------------------------------------------------------------- shared

    def _call_failed(self, target_id: str, level: str, detail: str) -> Outcome:
        return Outcome(
            target_id=target_id, level=level, model=self.model, verdict="needs_human",
            proposed=[], reasoning=f"model call failed: {detail}", confidence=0.0,
            accepted=False, failure="model_call_failed",
        )

    def _declined(self, target_id: str, level: str, proposal) -> Outcome:
        return Outcome(
            target_id=target_id,
            level=level,
            model=self.model,
            verdict=proposal.verdict,
            proposed=[],
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
            accepted=False,
            failure=None,
        )

    def _graded(self, target_id: str, level: str, proposal, ids: list[str], gate: GateResult) -> Outcome:
        return Outcome(
            target_id=target_id,
            level=level,
            model=self.model,
            verdict=proposal.verdict,
            proposed=list(ids),
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
            accepted=gate.accepted,
            failure=gate.failure,
            checks=gate.checks,
            detail=gate.detail,
        )
