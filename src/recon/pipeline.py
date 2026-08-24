"""End-to-end reconciliation: deterministic tiers, then model escalation of the residue."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from recon.agent.client import DEFAULT_MODEL, CachedLLM, GroqBackend
from recon.agent.escalate import Escalator, Outcome
from recon.domain.models import MatchRecord
from recon.matcher.config import DEFAULT_MATCHER_CONFIG, MatcherConfig
from recon.matcher.engine import Reconciler
from recon.matcher.invoices import InvoiceMatch, InvoiceMatcher, InvoiceResidue
from recon.matcher.normalise import load_sources
from recon.matcher.types import ReconResult, Sources


@dataclass
class PipelineResult:
    sources: Sources
    bank: ReconResult
    invoice_matches: list[InvoiceMatch] = field(default_factory=list)
    invoice_residue: list[InvoiceResidue] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    llm_stats: dict = field(default_factory=dict)


def run_pipeline(
    data_dir: Path,
    use_llm: bool = True,
    offline: bool = False,
    model: str = DEFAULT_MODEL,
    cfg: MatcherConfig = DEFAULT_MATCHER_CONFIG,
    llm: CachedLLM | None = None,
) -> PipelineResult:
    t0 = time.perf_counter()
    sources = load_sources(data_dir)
    t_load = time.perf_counter() - t0

    t0 = time.perf_counter()
    reconciler = Reconciler(sources, cfg)
    bank = reconciler.run()
    t_bank = time.perf_counter() - t0

    t0 = time.perf_counter()
    inv_matcher = InvoiceMatcher(sources.invoices, sources.settlements, cfg.fuzzy_threshold)
    invoice_matches, invoice_residue = inv_matcher.run()
    t_invoice = time.perf_counter() - t0

    result = PipelineResult(
        sources=sources,
        bank=bank,
        invoice_matches=invoice_matches,
        invoice_residue=invoice_residue,
        timings={"load_s": t_load, "bank_s": t_bank, "invoice_s": t_invoice, "llm_s": 0.0},
    )
    if not use_llm:
        return result

    t0 = time.perf_counter()
    if llm is None:
        backend = None if offline else GroqBackend()
        llm = CachedLLM(backend=backend, offline=offline)

    escalator = Escalator(llm, model=model, window_days=cfg.date_window_days,
                          tolerance_paise=cfg.tolerance_paise)

    settlements = {s.payment_id: s for s in sources.settlements}
    nets = {s.payment_id: s.net_paise for s in reconciler.settlements}
    available = [s for s in reconciler.settlements if s.payment_id not in reconciler.consumed]
    bank_rows = {b.txn_id: b for b in sources.bank}
    narrations = {b.txn_id: b.narration for b in sources.bank}

    escalator.escalate_bank(
        bank.exceptions, narrations, settlements, nets, available, reconciler.consumed, bank_rows
    )
    invoices = {i.invoice_id: i for i in sources.invoices}
    escalator.escalate_invoices(invoice_residue, settlements, invoices)

    result.outcomes = escalator.outcomes
    result.timings["llm_s"] = time.perf_counter() - t0
    result.llm_stats = dict(llm.stats)
    llm.save()

    _absorb(result, reconciler)
    return result


def _absorb(result: PipelineResult, reconciler: Reconciler) -> None:
    """Fold verified proposals into the results. Rejected ones stay exceptions."""
    accepted_bank = {o.target_id: o for o in result.outcomes if o.level == "bank" and o.accepted}
    accepted_inv = {o.target_id: o for o in result.outcomes if o.level == "invoice" and o.accepted}

    for txn_id, outcome in accepted_bank.items():
        result.bank.matches.append(
            MatchRecord(
                bank_txn_id=txn_id,
                payment_ids=sorted(outcome.proposed),
                invoice_ids=[],
                tier="llm_escalation",
                confidence=min(outcome.confidence, 0.7),
                evidence={"reasoning": outcome.reasoning, "gate": outcome.detail, "model": outcome.model},
                resolved_by="llm_verified",
            )
        )
    if accepted_bank:
        result.bank.matches.sort(key=lambda m: m.bank_txn_id)
        result.bank.exceptions = [
            e for e in result.bank.exceptions if e.bank_txn_id not in accepted_bank
        ]

    for payment_id, outcome in accepted_inv.items():
        result.invoice_matches.append(
            InvoiceMatch(
                payment_id=payment_id,
                invoice_ids=sorted(outcome.proposed),
                tier="llm_escalation",
                confidence=min(outcome.confidence, 0.7),
                evidence={"reasoning": outcome.reasoning, "model": outcome.model},
            )
        )
    if accepted_inv:
        result.invoice_matches.sort(key=lambda m: m.payment_id)
        result.invoice_residue = [
            r for r in result.invoice_residue if r.payment_id not in accepted_inv
        ]

    # Proposals the gate refused are recorded, not retried.
    for outcome in result.outcomes:
        if outcome.verdict == "match" and not outcome.accepted:
            for exc in result.bank.exceptions:
                if exc.bank_txn_id == outcome.target_id:
                    exc.reason_code = "llm_proposal_failed_verification"
                    exc.evidence = {
                        "model_said": outcome.proposed,
                        "model_reasoning": outcome.reasoning,
                        "model_confidence": outcome.confidence,
                        "gate_failure": outcome.failure,
                        "gate_detail": outcome.detail,
                    }
