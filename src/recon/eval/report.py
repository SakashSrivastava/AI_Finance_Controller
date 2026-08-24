"""Rendering: metrics.md, exceptions.csv, cash_position.md.

Precision leads every table. A wrong match on money is worse than no match, so match rate
is never the first number a reader sees.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from recon.controller.cash_position import CashPosition
from recon.domain.money import format_paise
from recon.matcher.types import ExceptionRow


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
        f"| Coverage | {m['coverage']:.2%} |",
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
        lines.append(
            f"| `{tag}` | {s['rows']} | {s['asserted']} | {s['precision']:.2%} "
            f"| {s['matchable']} | {s['recall']:.2%} |"
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
                    e.what_a_human_needs_to_check,
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
        f"| In flight (captured, not yet paid out) | {position.in_flight.count} | {format_paise(position.in_flight.paise)} |",
        f"| **Under investigation** | {position.under_investigation.count} | **{format_paise(position.under_investigation.paise)}** |",
        f"| Unresolvable from available data | {position.unresolvable.count} | {format_paise(position.unresolvable.paise)} |",
        "",
        "`Under investigation` is the rupee value a human still has to clear. It is the "
        "number a finance team acts on, and it is the reason an exception list matters "
        "more than a match rate.",
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
