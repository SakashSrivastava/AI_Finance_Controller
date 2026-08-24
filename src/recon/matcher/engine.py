"""The deterministic matching pipeline.

Tiers run in strict order and a payment leaves the candidate pool the moment it is
consumed, so a later, weaker tier can never re-assert money an earlier one already
attributed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from recon.domain.models import MatchRecord
from recon.matcher.config import DEFAULT_MATCHER_CONFIG, MatcherConfig
from recon.matcher.normalise import (
    index_by_settled_date,
    index_by_utr,
    looks_like_reversal,
    normalise_bank,
    normalise_settlements,
)
from recon.matcher.subsetsum import find_subsets
from recon.matcher.types import (
    ExceptionRow,
    NormalisedBank,
    NormalisedSettlement,
    ReasonCode,
    ReconResult,
    Sources,
)

OUT_OF_SCOPE_HINTS = (
    "SALARY",
    "GST PAYMENT",
    "RENT",
    "BANK CHARGES",
    "VENDOR PAYMENT",
    "CHALLAN",
)


class Reconciler:
    def __init__(self, sources: Sources, cfg: MatcherConfig = DEFAULT_MATCHER_CONFIG) -> None:
        self.cfg = cfg
        self.bank = normalise_bank(sources.bank)
        self.settlements = normalise_settlements(sources.settlements)
        self.by_utr = index_by_utr(self.settlements)
        self.by_date = index_by_settled_date(self.settlements)
        self.position = {b.txn_id: i for i, b in enumerate(self.bank)}

        self.consumed: set[str] = set()
        self.resolved: dict[str, MatchRecord] = {}
        self.hints: dict[str, dict] = {}
        self.stats: dict = defaultdict(int)

    # ------------------------------------------------------------------ public

    def run(self) -> ReconResult:
        self._collapse_duplicate_postings()
        self._classify_debits()
        self._tier1_utr_exact()
        self._tier2_batch_sum_in_window()
        self._tier3_subset_sum()
        self._tier4_tolerance()
        self._tier3_subset_sum(
            tolerance=self.cfg.tolerance_paise, tier="tier5_subset_with_tolerance"
        )
        return self._finalise()

    # ----------------------------------------------------------------- helpers

    def _unresolved(self) -> list[NormalisedBank]:
        return [b for b in self.bank if b.txn_id not in self.resolved]

    def _unresolved_credits(self) -> list[NormalisedBank]:
        return [b for b in self._unresolved() if b.is_credit]

    def _available(self, rows: list[NormalisedSettlement]) -> list[NormalisedSettlement]:
        return [s for s in rows if s.payment_id not in self.consumed]

    def _accept(
        self,
        bank: NormalisedBank,
        settlements: list[NormalisedSettlement],
        tier: str,
        confidence: float,
        evidence: dict,
        resolved_by: str = "deterministic",
    ) -> None:
        ids = sorted(s.payment_id for s in settlements)
        self.consumed.update(ids)
        self.resolved[bank.txn_id] = MatchRecord(
            bank_txn_id=bank.txn_id,
            payment_ids=ids,
            invoice_ids=[],
            tier=tier,
            confidence=confidence,
            evidence=evidence,
            resolved_by=resolved_by,  # type: ignore[arg-type]
        )
        self.stats[tier] += 1

    def _classify(self, bank: NormalisedBank, tier: str, evidence: dict) -> None:
        """Explain a row without asserting any money against it."""
        self.resolved[bank.txn_id] = MatchRecord(
            bank_txn_id=bank.txn_id,
            payment_ids=[],
            invoice_ids=[],
            tier=tier,
            confidence=1.0,
            evidence=evidence,
            resolved_by="deterministic",
        )
        self.stats[tier] += 1

    # ------------------------------------------------------------------- tiers

    def _collapse_duplicate_postings(self) -> None:
        """A credit, its reversal debit, and the repost are one event, not three.

        This must run before any UTR matching: all three rows carry the same UTR, so
        Tier 1 would otherwise attribute the batch to the earliest credit and leave the
        repost - the row that actually survives in the balance - unmatched.
        """
        by_amount: dict[int, list[NormalisedBank]] = defaultdict(list)
        for b in self.bank:
            if b.is_credit:
                by_amount[b.txn.credit_paise].append(b)

        for debit in [b for b in self.bank if not b.is_credit]:
            if not looks_like_reversal(debit.txn.narration) and debit.utr is None:
                continue
            candidates = by_amount.get(debit.txn.debit_paise, [])
            window = self.cfg.dup_window_days
            pos = self.position[debit.txn_id]
            before = [
                c
                for c in candidates
                if self.position[c.txn_id] < pos
                and 0 <= (debit.txn.value_date - c.txn.value_date).days <= window
                and c.txn_id not in self.resolved
            ]
            after = [
                c
                for c in candidates
                if self.position[c.txn_id] > pos
                and 0 <= (c.txn.value_date - debit.txn.value_date).days <= window
                and c.txn_id not in self.resolved
            ]
            # The UTR disambiguates, but it must not eliminate: one leg of the group may
            # have lost its UTR to a capped narration while the others kept theirs. Prefer
            # within each side independently, never across the whole pool.
            if debit.utr:
                before = [c for c in before if c.utr == debit.utr] or before
                after = [c for c in after if c.utr == debit.utr] or after
            if not before or not after:
                continue

            original = max(before, key=lambda c: self.position[c.txn_id])
            repost = min(after, key=lambda c: self.position[c.txn_id])
            evidence = {
                "group": [original.txn_id, debit.txn_id, repost.txn_id],
                "amount_paise": debit.txn.debit_paise,
                "survivor": repost.txn_id,
            }
            self._classify(original, "tier0_dup_original", evidence)
            self._classify(debit, "tier0_dup_reversal", evidence)
            self.stats["dup_groups"] += 1

    def _classify_debits(self) -> None:
        for b in self._unresolved():
            if b.is_credit:
                continue
            text = b.txn.narration.upper()
            if any(h in text for h in OUT_OF_SCOPE_HINTS):
                self._classify(b, "tier0_out_of_scope_debit", {"narration": b.txn.narration})

    def _tier1_utr_exact(self) -> None:
        """A UTR match alone is not a match. The money has to close as well."""
        for b in self._unresolved_credits():
            if not b.utr:
                continue
            batch = self._available(self.by_utr.get(b.utr, []))
            if not batch:
                continue
            total = sum(s.net_paise for s in batch)
            if total == b.txn.credit_paise:
                self._accept(
                    b,
                    batch,
                    tier="tier1_utr_exact",
                    confidence=1.0,
                    evidence={
                        "utr": b.utr,
                        "batch_size": len(batch),
                        "batch_net_paise": total,
                        "credit_paise": b.txn.credit_paise,
                        "delta_paise": 0,
                    },
                )
            else:
                self.hints[b.txn_id] = {
                    "reason": ReasonCode.UTR_MATCHED_AMOUNT_MISMATCH,
                    "utr": b.utr,
                    "batch_net_paise": total,
                    "credit_paise": b.txn.credit_paise,
                    "delta_paise": b.txn.credit_paise - total,
                    "candidates": sorted(s.payment_id for s in batch),
                }
                self.stats["utr_hit_amount_mismatch"] += 1

    def _window_settlements(self, bank: NormalisedBank) -> list[NormalisedSettlement]:
        """Unconsumed settlements whose settled_at falls in the lookback window."""
        rows = []
        for offset in range(self.cfg.date_window_days + 1):
            day = bank.txn.value_date - timedelta(days=offset)
            rows.extend(s for s in self.by_date.get(day, []) if s.payment_id not in self.consumed)
        return rows

    def _tier2_batch_sum_in_window(self) -> None:
        """No usable UTR. Look for a whole batch in the window that sums to the credit."""
        for b in self._unresolved_credits():
            groups: dict[str, list[NormalisedSettlement]] = defaultdict(list)
            for s in self._window_settlements(b):
                groups[s.row.utr].append(s)

            hits = [
                (utr, rows)
                for utr, rows in groups.items()
                if sum(r.net_paise for r in rows) == b.txn.credit_paise
            ]
            if len(hits) == 1:
                utr, rows = hits[0]
                self._accept(
                    b,
                    rows,
                    tier="tier2_batch_sum_window",
                    confidence=0.95,
                    evidence={
                        "utr": utr,
                        "matched_on": "exact batch sum inside date window",
                        "window_days": self.cfg.date_window_days,
                        "batch_size": len(rows),
                        "credit_paise": b.txn.credit_paise,
                        "delta_paise": 0,
                    },
                )
            elif len(hits) > 1:
                # An ambiguous match is not a match.
                self.hints[b.txn_id] = {
                    "reason": ReasonCode.AMBIGUOUS_MULTIPLE_BATCHES,
                    "batches": sorted(utr for utr, _ in hits),
                    "candidates": sorted(r.payment_id for _, rows in hits for r in rows),
                }
                self.stats["ambiguous_batches"] += 1

    def _subset_for_batch(
        self, bank: NormalisedBank, pool: list[NormalisedSettlement], tolerance: int
    ) -> tuple[str, list[NormalisedSettlement]]:
        """Search one batch. Refunds and chargebacks are folded into the target rather
        than offered as free candidates (CONVENTIONS.md section 7)."""
        negatives = [s for s in pool if s.net_paise < 0]
        positives = [s for s in pool if s.net_paise >= 0]
        target = bank.txn.credit_paise - sum(s.net_paise for s in negatives)
        if target < 0 or not positives:
            return "none", []

        result = find_subsets(
            [s.net_paise for s in positives],
            target=target,
            max_size=self.cfg.max_subset_size,
            node_budget=self.cfg.node_budget,
            tolerance=tolerance,
        )
        self.stats["subset_nodes"] += result.nodes
        if result.budget_exceeded:
            return "budget", []
        if result.is_ambiguous:
            return "ambiguous", []
        if result.is_unique:
            return "unique", [positives[i] for i in result.solutions[0]] + negatives
        return "none", []

    def _tier3_subset_sum(self, tolerance: int = 0, tier: str = "tier3_subset_sum") -> None:
        """The batch is only partly paid out: some captured payments were held back."""
        for b in self._unresolved_credits():
            hint = self.hints.get(b.txn_id, {})
            if hint.get("reason") == ReasonCode.UTR_MATCHED_AMOUNT_MISMATCH:
                batches = {hint["utr"]: self._available(self.by_utr.get(hint["utr"], []))}
                confidence = 0.9
            else:
                grouped: dict[str, list[NormalisedSettlement]] = defaultdict(list)
                for s in self._window_settlements(b):
                    grouped[s.row.utr].append(s)
                batches = dict(grouped)
                confidence = 0.75

            hits: list[tuple[str, list[NormalisedSettlement]]] = []
            ambiguous = exceeded = False
            for utr, pool in batches.items():
                kind, chosen = self._subset_for_batch(b, pool, tolerance)
                if kind == "unique":
                    hits.append((utr, chosen))
                elif kind == "ambiguous":
                    ambiguous = True
                elif kind == "budget":
                    exceeded = True

            if ambiguous or len(hits) > 1:
                self.hints[b.txn_id] = {
                    "reason": ReasonCode.AMBIGUOUS_MULTIPLE_SUBSETS,
                    "candidates": sorted(s.payment_id for _, rows in hits for s in rows),
                    "note": "more than one subset reconciles to this credit",
                }
                self.stats["ambiguous_subsets"] += 1
            elif len(hits) == 1:
                utr, chosen = hits[0]
                held = [
                    s.payment_id
                    for s in self._available(self.by_utr.get(utr, []))
                    if s not in chosen
                ]
                self._accept(
                    b,
                    chosen,
                    tier=tier,
                    confidence=confidence if tolerance == 0 else confidence - 0.15,
                    evidence={
                        "utr": utr,
                        "matched_on": "subset of the batch reconciles to the credit",
                        "subset_size": len(chosen),
                        "withheld_from_payout": sorted(held),
                        "credit_paise": b.txn.credit_paise,
                        "tolerance_paise": tolerance,
                    },
                )
                self.hints.pop(b.txn_id, None)
            elif exceeded and not hint:
                self.hints[b.txn_id] = {
                    "reason": ReasonCode.SUBSET_SEARCH_BUDGET_EXCEEDED,
                    "candidates": [],
                }
                self.stats["subset_budget_exceeded"] += 1

    def _tier4_tolerance(self) -> None:
        """Rounding drift only. Tolerance is allowed only where the candidate is already
        uniquely determined, otherwise a loose band manufactures matches."""
        tol = self.cfg.tolerance_paise
        for b in self._unresolved_credits():
            hint = self.hints.get(b.txn_id, {})
            if hint.get("reason") != ReasonCode.UTR_MATCHED_AMOUNT_MISMATCH:
                continue
            if abs(hint["delta_paise"]) > tol:
                continue
            batch = self._available(self.by_utr.get(hint["utr"], []))
            if not batch:
                continue
            self._accept(
                b,
                batch,
                tier="tier4_tolerance",
                confidence=0.8,
                evidence={
                    "utr": hint["utr"],
                    "matched_on": "UTR exact, amount within rounding tolerance",
                    "tolerance_paise": tol,
                    "delta_paise": hint["delta_paise"],
                    "credit_paise": b.txn.credit_paise,
                },
            )
            self.hints.pop(b.txn_id, None)

    # --------------------------------------------------------------- finalise

    def _finalise(self) -> ReconResult:
        exceptions = []
        for b in self._unresolved():
            hint = self.hints.get(b.txn_id, {})
            if hint:
                reason = hint["reason"]
                candidates = hint.get("candidates", [])
            elif not b.is_credit:
                reason = ReasonCode.UNEXPLAINED_DEBIT
                candidates = []
            else:
                reason = ReasonCode.NO_GATEWAY_COUNTERPART
                candidates = []
            exceptions.append(
                ExceptionRow(
                    bank_txn_id=b.txn_id,
                    value_date=b.txn.value_date,
                    amount_paise=b.amount_paise,
                    reason_code=reason,
                    closest_candidates=candidates[:10],
                    evidence=hint,
                )
            )

        self.stats["bank_rows"] = len(self.bank)
        self.stats["resolved"] = len(self.resolved)
        self.stats["exceptions"] = len(exceptions)
        self.stats["payments_consumed"] = len(self.consumed)
        return ReconResult(
            matches=[self.resolved[k] for k in sorted(self.resolved)],
            exceptions=sorted(exceptions, key=lambda e: e.bank_txn_id),
            stats=dict(self.stats),
        )
