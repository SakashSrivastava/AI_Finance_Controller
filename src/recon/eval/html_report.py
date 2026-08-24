"""A single self-contained HTML report.

No server, no build step, no external requests - it opens instantly from disk and screen
records cleanly. Precision leads; the exception queue is shown rather than hidden.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Template

from recon.controller.cash_position import CashPosition
from recon.domain.money import format_paise
from recon.matcher.types import ExceptionRow

TEMPLATE = Template(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reconciliation report</title>
<style>
  :root {
    --bg:#ffffff; --fg:#12151a; --muted:#5b6472; --line:#e3e7ee;
    --panel:#f7f9fc; --accent:#0b5cff; --good:#0a7c42; --bad:#b3261e; --warn:#8a5a00;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f1216; --fg:#e8ecf2; --muted:#98a2b3; --line:#242a33;
            --panel:#161b22; --accent:#6f9bff; --good:#4ade80; --bad:#ff6b6b; --warn:#e0b341; }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  .wrap { max-width:1080px; margin:0 auto; padding:40px 24px 80px; }
  h1 { font-size:30px; margin:0 0 4px; letter-spacing:-0.02em; }
  h2 { font-size:19px; margin:44px 0 12px; letter-spacing:-0.01em; }
  .sub { color:var(--muted); margin:0 0 28px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px 18px; }
  .card .k { font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }
  .card .v { font-size:27px; font-weight:650; margin-top:6px; letter-spacing:-0.02em; }
  .good { color:var(--good); } .bad { color:var(--bad); } .warn { color:var(--warn); }
  .scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; }
  table { border-collapse:collapse; width:100%; font-size:14px; }
  th,td { text-align:left; padding:8px 12px; border-bottom:1px solid var(--line); white-space:nowrap; }
  th { color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
  td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
  code { background:var(--panel); padding:1px 6px; border-radius:4px; font-size:13px; }
  .note { color:var(--muted); font-size:14px; margin:10px 0 0; }
  .rule { border:0; border-top:1px solid var(--line); margin:36px 0 0; }
</style></head><body><div class="wrap">

<h1>Reconciliation report</h1>
<p class="sub">{{ dataset }} &middot; {{ bank_rows }} bank rows &middot; {{ payments }} payments
{% if holdout %}&middot; <strong>held-out seed, never used for tuning</strong>{% endif %}</p>

<div class="cards">
  <div class="card"><div class="k">Precision (strict)</div><div class="v good">{{ '%.2f'|format(m.precision_strict*100) }}%</div></div>
  <div class="card"><div class="k">Recall (strict)</div><div class="v">{{ '%.2f'|format(m.recall_strict*100) }}%</div></div>
  <div class="card"><div class="k">False matches</div><div class="v {{ 'good' if m.false_matches==0 else 'bad' }}">{{ m.false_matches }}</div></div>
  <div class="card"><div class="k">Coverage</div><div class="v">{{ '%.1f'|format(m.coverage*100) }}%</div></div>
  <div class="card"><div class="k">Exceptions</div><div class="v warn">{{ m.exceptions }}</div></div>
</div>
<p class="note">Agreement is <strong>strict set equality</strong>: four of five payments right is a
wrong answer, because the money does not reconcile. Mean Jaccard overlap is
{{ '%.3f'|format(m.mean_jaccard) }}, which distinguishes near misses from wild guesses.</p>

{% if m.llm %}
<h2>Model escalation and the verification gate</h2>
<div class="cards">
  <div class="card"><div class="k">Escalated</div><div class="v">{{ m.llm.escalated }}</div></div>
  <div class="card"><div class="k">Proposed a match</div><div class="v">{{ m.llm.proposed_match }}</div></div>
  <div class="card"><div class="k">Accepted by gate</div><div class="v good">{{ m.llm.accepted }}</div></div>
  <div class="card"><div class="k">Rejected by gate</div><div class="v {{ 'bad' if m.llm.failed_verification else '' }}">{{ m.llm.failed_verification }}</div></div>
</div>
<p class="note">Model <code>{{ m.llm.model }}</code>. Every proposal is re-derived arithmetically
before it becomes an assertion. Rejected proposals are recorded as
<code>llm_proposal_failed_verification</code> and handed to a human &mdash; never retried,
never downgraded into a weaker match.</p>
{% endif %}

<h2>Resolution by tier</h2>
<div class="scroll"><table>
<thead><tr><th>Tier</th><th class="num">Rows</th></tr></thead><tbody>
{% for tier, n in m.by_tier.items() %}<tr><td><code>{{ tier }}</code></td><td class="num">{{ n }}</td></tr>{% endfor %}
</tbody></table></div>

<h2>Per case type</h2>
<p class="note">Where the system is strong and where it is not.</p>
<div class="scroll"><table>
<thead><tr><th>Case type</th><th class="num">Rows</th><th class="num">Asserted</th><th class="num">Precision</th><th class="num">Matchable</th><th class="num">Recall</th></tr></thead><tbody>
{% for tag, s in m.by_case_type|dictsort %}
<tr><td><code>{{ tag }}</code></td><td class="num">{{ s.rows }}</td><td class="num">{{ s.asserted }}</td>
<td class="num">{{ '%.1f'|format(s.precision*100) }}%</td><td class="num">{{ s.matchable }}</td>
<td class="num">{{ '%.1f'|format(s.recall*100) }}%</td></tr>
{% endfor %}
</tbody></table></div>

<h2>Cash position <span style="font-weight:400;color:var(--muted);font-size:15px">as of {{ cash.as_of }}</span></h2>
<div class="scroll"><table>
<thead><tr><th>Where the money is</th><th class="num">Count</th><th class="num">Value</th></tr></thead><tbody>
<tr><td>Settled and in the bank</td><td class="num">{{ cash.settled.count }}</td><td class="num">{{ fmt(cash.settled.paise) }}</td></tr>
<tr><td>In flight (captured, not yet paid out)</td><td class="num">{{ cash.in_flight.count }}</td><td class="num">{{ fmt(cash.in_flight.paise) }}</td></tr>
<tr><td><strong>Under investigation</strong></td><td class="num">{{ cash.under_investigation.count }}</td><td class="num"><strong>{{ fmt(cash.under_investigation.paise) }}</strong></td></tr>
<tr><td>Unresolvable from available data</td><td class="num">{{ cash.unresolvable.count }}</td><td class="num">{{ fmt(cash.unresolvable.paise) }}</td></tr>
<tr><td>Total receivables outstanding</td><td class="num"></td><td class="num">{{ fmt(cash.total_receivables_paise) }}</td></tr>
<tr><td>Gateway fees + GST</td><td class="num"></td><td class="num">{{ fmt(cash.fees_paise + cash.gst_paise) }}</td></tr>
</tbody></table></div>

<h2>Exception queue</h2>
<p class="note">{{ exceptions|length }} unresolved. Split into what a human could clear with
more context, and what is genuinely unresolvable from the three available sources.</p>
<div class="scroll"><table>
<thead><tr><th>Bank txn</th><th>Date</th><th class="num">Amount</th><th>Reason</th><th>Resolvable?</th></tr></thead><tbody>
{% for e in exceptions %}
<tr><td><code>{{ e.bank_txn_id }}</code></td><td>{{ e.value_date }}</td>
<td class="num">{{ fmt(e.amount_paise) }}</td><td><code>{{ e.reason_code }}</code></td>
<td>{{ 'with context' if e.resolvable_with_context else 'no' }}</td></tr>
{% endfor %}
</tbody></table></div>

<hr class="rule">
<p class="note">Synthetic data, generated from a fixed seed. Tuning was done on seed 42;
these numbers are from {{ 'unseen seed 7' if holdout else 'seed 42' }}.
Deterministic matching ran {{ records }} records in {{ '%.3f'|format(det_seconds) }}s
({{ '{:,.0f}'.format(records/det_seconds) }} records/second).</p>

</div></body></html>"""
)


def write_html_report(
    metrics: dict,
    cash: CashPosition,
    exceptions: list[ExceptionRow],
    out_path: Path,
    dataset: str = "seed 42",
    holdout: bool = False,
) -> None:
    timings = metrics.get("timings", {})
    det = max(timings.get("bank_s", 0) + timings.get("invoice_s", 0), 1e-6)
    records = metrics["bank_rows"] + metrics.get("invoice_level", {}).get("payments", 0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        TEMPLATE.render(
            m=metrics,
            cash=cash,
            exceptions=sorted(exceptions, key=lambda e: e.bank_txn_id),
            fmt=format_paise,
            dataset=dataset,
            holdout=holdout,
            bank_rows=metrics["bank_rows"],
            payments=metrics.get("invoice_level", {}).get("payments", 0),
            records=records,
            det_seconds=det,
        ),
        encoding="utf-8",
    )
