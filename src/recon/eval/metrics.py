"""Evaluation against ground truth.

This is the only package permitted to read the ground truth files. A test asserts that
nothing under src/recon/matcher or src/recon/agent references them.

Definitions, stated explicitly because they decide what the headline number means:

* A match is a *set* of payment ids, so agreement is **strict set equality**. Getting
  four of five payments in a batch right is a wrong answer, because the money does not
  reconcile. Strict precision is the headline.
* Mean Jaccard overlap is reported alongside it to separate near misses from wild
  guesses. Those are different diagnoses.
* Rows the pipeline explains *without* asserting money against them - a reversal leg, an
  out-of-scope debit - are classifications, not money matches. They count towards
  coverage and are scored separately, never inside precision.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from recon.domain.csvio import read_models
from recon.domain.models import BankTxn, GroundTruthBank, Settlement
from recon.matcher.normalise import extract_utr
from recon.matcher.types import ReconResult


def _safe(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return _safe(len(a & b), len(a | b))


def evaluate(data_dir: Path, result: ReconResult) -> dict:
    gt_rows = read_models(data_dir / "ground_truth_bank.csv", GroundTruthBank)
    truth = {g.bank_txn_id: set(g.payment_ids) for g in gt_rows}
    tags = {g.bank_txn_id: g.case_tags for g in gt_rows}
    bank = {b.txn_id: b for b in read_models(data_dir / "bank_statement.csv", BankTxn)}
    settlements = read_models(data_dir / "gateway_settlements.csv", Settlement)

    asserted = [m for m in result.matches if m.payment_ids]
    classified = [m for m in result.matches if not m.payment_ids]

    correct = [m for m in asserted if set(m.payment_ids) == truth.get(m.bank_txn_id, set())]
    wrong = [m for m in asserted if set(m.payment_ids) != truth.get(m.bank_txn_id, set())]
    jaccards = [
        _jaccard(set(m.payment_ids), truth.get(m.bank_txn_id, set())) for m in asserted
    ]

    matchable = [txn_id for txn_id, ids in truth.items() if ids]
    found = {m.bank_txn_id for m in correct}

    # The worst error class: asserting money against a credit that has no counterpart.
    unresolvable_ids = {t for t, tg in tags.items() if "unresolvable" in tg}
    false_on_unresolvable = [m for m in asserted if m.bank_txn_id in unresolvable_ids]

    # Classifications (empty payment sets) are scored on their own terms.
    classified_correct = [m for m in classified if not truth.get(m.bank_txn_id, set())]

    metrics = {
        "bank_rows": len(bank),
        "coverage": _safe(len(result.matches), len(bank)),
        "asserted_matches": len(asserted),
        "precision_strict": _safe(len(correct), len(asserted)),
        "mean_jaccard": _safe(sum(jaccards), len(jaccards)),
        "recall_strict": _safe(len(found), len(matchable)),
        "false_matches": len(wrong),
        "false_match_rate": _safe(len(wrong), len(asserted)),
        "false_matches_on_unresolvable": len(false_on_unresolvable),
        "classifications": len(classified),
        "classification_accuracy": _safe(len(classified_correct), len(classified)),
        "exceptions": len(result.exceptions),
        "utr_extraction_recall": _utr_extraction_recall(bank, gt_rows, settlements),
        "by_tier": _by_tier(result),
        "by_case_type": _by_case_type(asserted, truth, tags, matchable, found),
        "exceptions_by_reason": _by_reason(result),
        "unresolved_value_paise": sum(e.amount_paise for e in result.exceptions),
    }
    return metrics


def _utr_extraction_recall(
    bank: dict[str, BankTxn], gt_rows: list[GroundTruthBank], settlements: list[Settlement]
) -> dict:
    """Two different questions, both worth answering.

    `parser_recall` - when the narration does carry the full UTR, does Tier 0 pull it
    out? This grades the regex set.

    `utr_available` - what share of settlement credits yield a usable UTR at all, once
    missing and capped narrations are accounted for? This is the ceiling on Tier 1 and
    therefore the size of the job left for the amount-based tiers.
    """
    utr_of = {s.payment_id: s.utr for s in settlements}
    present = extracted = credits = usable = 0
    for g in gt_rows:
        if not g.payment_ids:
            continue
        credits += 1
        utr = utr_of.get(g.payment_ids[0])
        narration = bank[g.bank_txn_id].narration.upper()
        parsed = extract_utr(narration)[0]
        if parsed and parsed == utr:
            usable += 1
        if utr and utr in narration:
            present += 1
            if parsed == utr:
                extracted += 1
    return {
        "narrations_carrying_utr": present,
        "parsed": extracted,
        "parser_recall": _safe(extracted, present),
        "settlement_credits": credits,
        "utr_available": _safe(usable, credits),
    }


def _by_tier(result: ReconResult) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for m in result.matches:
        counts[m.tier] += 1
    return dict(sorted(counts.items()))


def _by_reason(result: ReconResult) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for e in result.exceptions:
        counts[e.reason_code] += 1
    return dict(sorted(counts.items()))


def _by_case_type(
    asserted: list,
    truth: dict[str, set[str]],
    tags: dict[str, list[str]],
    matchable: list[str],
    found: set[str],
) -> dict:
    all_tags = sorted({t for tg in tags.values() for t in tg})
    out = {}
    for tag in all_tags:
        tagged = {t for t, tg in tags.items() if tag in tg}
        tag_asserted = [m for m in asserted if m.bank_txn_id in tagged]
        tag_correct = [m for m in tag_asserted if set(m.payment_ids) == truth[m.bank_txn_id]]
        tag_matchable = [t for t in matchable if t in tagged]
        out[tag] = {
            "rows": len(tagged),
            "asserted": len(tag_asserted),
            "precision": _safe(len(tag_correct), len(tag_asserted)),
            "matchable": len(tag_matchable),
            "recall": _safe(len([t for t in tag_matchable if t in found]), len(tag_matchable)),
        }
    return out
