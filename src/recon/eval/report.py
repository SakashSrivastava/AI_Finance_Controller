"""Rendering: metrics.md, exceptions.csv, cash_position.md.

Precision leads every table. A wrong match on money is worse than no match, so match rate
is never the first number a reader sees.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from recon.controller.cash_position import CashPosition
from recon.domain.money import format_paise
from recon.controller.ledger import Ledger
from recon.matcher.types import HUMAN_ACTION, ExceptionRow


def write_metrics(metrics: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "metrics.md").write_text(render_markdown(metrics), encoding="utf-8")


def render_markdown(m: dict) -> str:
    utr = m["utr_extraction_recall"]
    lines = [
        "# Reconciliation results",
        "",
        "## Headline",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| **Precision (strict set equality)** | **{m['precision_strict']:.2%}** |",
        f"| Recall (strict) | {m['recall_strict']:.2%} |",
        f"| Mean Jaccard overlap | {m['mean_jaccard']:.3f} |",
        f"| False matches | {m['false_matches']} of {m['asserted_matches']} asserted |",
        f"| False matches on unresolvable rows | {m['false_matches_on_unresolvable']} |",
        f"| Match rate | {m['match_rate']:.2%} |",
        f"| Coverage (any verdict, including explained non-matches) | {m['coverage']:.2%} |",
        f"| Bank rows | {m['bank_rows']} |",
        f"| Exceptions | {m['exceptions']} |",
        f"| Value under investigation | {format_paise(m['unresolved_value_paise'])} |",
        "",
        "Agreement is **strict set equality**: a match is a set of payment ids, and getting "
        "four of five right is a wrong answer because the money does not reconcile. Mean "
        "Jaccard is reported alongside so near misses can be told apart from wild guesses.",
        "",
        "## UTR extraction",
        "",
        f"- Parser recall (UTR present in narration): **{utr['parser_recall']:.2%}** "
        f"({utr['parsed']}/{utr['narrations_carrying_utr']})",
        f"- UTR available at all (after missing and capped narrations): "
        f"**{utr['utr_available']:.2%}** of {utr['settlement_credits']} settlement credits",
        "",
        "The second number is the ceiling on UTR matching and therefore the size of the job "
        "left to the amount-based tiers.",
        "",
        "## Resolution by tier",
        "",
        "| Tier | Rows |",
        "|---|---|",
    ]
    for tier, count in m["by_tier"].items():
        lines.append(f"| `{tier}` | {count} |")

    lines += ["", "## Exceptions by reason", "", "| Reason | Rows |", "|---|---|"]
    for reason, count in m["exceptions_by_reason"].items():
        lines.append(f"| `{reason}` | {count} |")

    lines += [
        "",
        "## Per case type",
        "",
        "Where the system is strong and where it is not.",
        "",
        "| Case type | Rows | Asserted | Precision | Matchable | Recall |",
        "|---|---|---|---|---|---|",
    ]
    for tag, s in sorted(m["by_case_type"].items()):
        # A row with nothing to assert has no precision. Printing 0.00% there reads as
        # failure when it means "not applicable" - a reversal leg carries no money.
        precision = f"{s['precision']:.2%}" if s["asserted"] else "—"
        recall = f"{s['recall']:.2%}" if s["matchable"] else "—"
        lines.append(
            f"| `{tag}` | {s['rows']} | {s['asserted']} | {precision} "
            f"| {s['matchable']} | {recall} |"
        )

    if m.get("llm"):
        llm = m["llm"]
        lines += [
            "",
            "## Model escalation",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Model | `{llm.get('model', '')}` |",
            f"| Items escalated | {llm['escalated']} |",
            f"| Proposed a match | {llm['proposed_match']} |",
            f"| Declined (no_match / needs_human) | {llm['declined']} |",
            f"| **Accepted by the verification gate** | **{llm['accepted']}** |",
            f"| **Rejected by the verification gate** | **{llm['failed_verification']}** |",
            "",
            "Rejected proposals are recorded as `llm_proposal_failed_verification` and "
            "handed to a human. They are never retried or downgraded into a weaker match.",
        ]
        if llm.get("gate_failures"):
            lines += ["", "| Gate failure | Count |", "|---|---|"]
            for reason, count in sorted(llm["gate_failures"].items()):
                lines.append(f"| `{reason}` | {count} |")

    return "\n".join(lines) + "\n"


def write_exceptions(exceptions: list[ExceptionRow], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    columns = [
        "bank_txn_id",
        "value_date",
        "amount_paise",
        "amount",
        "reason_code",
        "resolvable_with_context",
        "closest_candidates",
        "what_a_human_needs_to_check",
    ]
    with (out_dir / "exceptions.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(columns)
        for e in sorted(exceptions, key=lambda x: x.bank_txn_id):
            writer.writerow(
                [
                    e.bank_txn_id,
                    e.value_date.isoformat(),
                    e.amount_paise,
                    format_paise(e.amount_paise),
                    e.reason_code,
                    "yes" if e.resolvable_with_context else "no",
                    "|".join(e.closest_candidates),
                    e.what_a_human_needs_to_check or HUMAN_ACTION.get(e.reason_code, ""),
                ]
            )


def render_cash_position(position: CashPosition) -> str:
    lines = [
        "# Cash position",
        "",
        f"As of **{position.as_of}**.",
        "",
        "| Where the money is | Count | Value |",
        "|---|---|---|",
        f"| Settled and in the bank | {position.settled.count} | {format_paise(position.settled.paise)} |",
        f"| In flight (settled within the last {3} days, not yet on the statement) | {position.in_flight.count} | {format_paise(position.in_flight.paise)} |",
        f"| Settled but unattributed | {position.settled_but_unattributed.count} | {format_paise(position.settled_but_unattributed.paise)} |",
        f"| **Under investigation** | {position.under_investigation.count} | **{format_paise(position.under_investigation.paise)}** |",
        f"| Unresolvable from available data | {position.unresolvable.count} | {format_paise(position.unresolvable.paise)} |",
        "",
        "`Under investigation` is the rupee value a human still has to clear, counted on "
        "the bank side. It is the number a finance team acts on, and it is the reason an "
        "exception list matters more than a match rate.",
        "",
        "`Settled but unattributed` is the gateway-side view, and it deliberately mixes two "
        "things this data cannot separate: payments the gateway withheld against a reserve "
        "or a risk review, and payments it did pay out that could not be tied to a specific "
        "credit. Distinguishing them needs the gateway's own payout report. It is kept apart "
        "from `in flight` because treating either as incoming cash would overstate the "
        "position.",
        "",
        "## Receivables",
        "",
        "| Ageing | Invoices | Value |",
        "|---|---|---|",
        f"| Not yet due | {position.not_yet_due.count} | {format_paise(position.not_yet_due.paise)} |",
    ]
    for label, bucket in position.overdue.items():
        lines.append(f"| Overdue {label} days | {bucket.count} | {format_paise(bucket.paise)} |")
    lines += [
        f"| **Total receivables** | | **{format_paise(position.total_receivables_paise)}** |",
        "",
        "## Cost of collection",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Gateway fees | {format_paise(position.fees_paise)} |",
        f"| GST on fees | {format_paise(position.gst_paise)} |",
        f"| **Total** | **{format_paise(position.fees_paise + position.gst_paise)}** |",
    ]
    return "\n".join(lines) + "\n"


def write_cash_position(position: CashPosition, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cash_position.md").write_text(render_cash_position(position), encoding="utf-8")


def render_ledger(ledger: Ledger, exception_value_paise: int) -> str:
    """The books: a trial balance plus the tie-out that makes it checkable."""
    trial = ledger.trial_balance()
    lines = [
        "# The books",
        "",
        f"{len(ledger.entries)} journal entries, one per bank transaction, derived entirely "
        "from the reconciliation.",
        "",
        "## Trial balance",
        "",
        "| Account | | Balance |",
        "|---|---|---|",
    ]
    for account, balance in trial.items():
        side = "Dr" if balance >= 0 else "Cr"
        lines.append(f"| {account} | {side} | {format_paise(abs(balance))} |")
    lines += [
        "",
        f"| **Total debits** | | **{format_paise(ledger.total_debits)}** |",
        f"| **Total credits** | | **{format_paise(ledger.total_credits)}** |",
        "",
        f"**Balanced: {ledger.balances}**",
        "",
        "## Why this is a check and not a rendering",
        "",
        "Double entry is an arithmetic invariant over the whole reconciliation that never "
        "consults the matcher's logic. If a batch were mis-attributed in a way that moved "
        "amounts, the trial balance would stop closing.",
        "",
        "The tie-out below is the same idea. The exception queue is produced by the matcher; "
        "the suspense balance falls out of bookkeeping over every bank row. Two independent "
        "routes, one number.",
        "",
        "| | Value |",
        "|---|---|",
        f"| Suspense balance | {format_paise(abs(ledger.suspense_paise))} |",
        f"| Exception queue | {format_paise(exception_value_paise)} |",
        f"| **Agree** | **{abs(ledger.suspense_paise) == exception_value_paise}** |",
        "",
        "Gateway fees and the GST on them never arrive as a payment - they are netted before "
        "the money reaches the bank. Reconstructing them from the fee model is the only way "
        "they are ever recorded, and the GST input credit is real money the merchant can "
        "claim back.",
    ]
    return "\n".join(lines) + "\n"


def write_ledger(ledger: Ledger, exception_value_paise: int, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ledger.md").write_text(
        render_ledger(ledger, exception_value_paise), encoding="utf-8"
    )


def render_gate_rejections(outcomes: list, model: str) -> str:
    """Every proposal the gate refused, with the model's own words beside the arithmetic.

    Committed so the claims in the README are checkable without rerunning anything and
    without an API key. Citing evidence that is not in the repository is not evidence.
    """
    refused = [o for o in outcomes if o.verdict == "match" and not o.accepted]
    lines = [
        "# Proposals the verification gate refused",
        "",
        f"Model `{model}`, held-out seed. {len(refused)} of "
        f"{sum(1 for o in outcomes if o.verdict == 'match')} proposals refused.",
        "",
        "Reproduce with `recon compare --data data/7` - it replays the committed cache, so "
        "no API key is needed.",
        "",
    ]
    if not refused:
        lines.append("No proposals were refused in this run.")
        return "\n".join(lines) + "\n"

    for o in refused:
        lines += [
            f"## `{o.target_id}` - {o.failure}",
            "",
            f"**The model proposed** `{sorted(o.proposed)}` at confidence {o.confidence}.",
            "",
            "> " + o.reasoning.replace("\n", " "),
            "",
            "**The gate checked:**",
            "",
            "| Check | Result |",
            "|---|---|",
        ]
        for check, passed in o.checks.items():
            lines.append(f"| `{check}` | {'pass' if passed else '**FAIL**'} |")
        if o.detail:
            lines += ["", "**Arithmetic:**", "", "```json", _pretty(o.detail), "```"]
        lines.append("")
    return "\n".join(lines) + "\n"


def _pretty(detail: dict) -> str:
    return json.dumps(detail, indent=2, sort_keys=True)


def write_gate_rejections(outcomes: list, model: str, out_dir: Path) -> None:
    """One file per model. A run of the stronger model refuses nothing, and must not be
    able to overwrite the weaker model's rejections - that is the evidence the README
    cites."""
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", model).strip("-").lower()
    (out_dir / f"gate_rejections.{slug}.md").write_text(
        render_gate_rejections(outcomes, model), encoding="utf-8"
    )
