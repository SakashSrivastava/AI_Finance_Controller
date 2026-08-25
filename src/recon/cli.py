"""Command line interface."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import typer
from dotenv import load_dotenv

# Windows consoles default to cp1252, which cannot encode the rupee sign. Without this
# the demo dies mid-run on its own output.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

app = typer.Typer(add_completion=False, help="Multi-source reconciliation agent.")


def _echo(label: str, value: str) -> None:
    typer.echo(f"  {label:<38} {value}")


@app.command()
def generate(
    seed: int = typer.Option(42, help="Same seed produces byte-identical data."),
    n: int = typer.Option(250, help="Number of bank transaction slots."),
    out: Path = typer.Option(None, help="Output directory (defaults to data/<seed>)."),
) -> None:
    """Generate the synthetic three-source dataset and its ground truth."""
    from dataclasses import replace

    from recon.generator.build import build, write_dataset
    from recon.generator.config import DEFAULT_CONFIG

    cfg = replace(DEFAULT_CONFIG, n_bank_txns=n)
    target = out or Path("data") / str(seed)
    t0 = time.perf_counter()
    ds = build(seed, cfg)
    write_dataset(ds, target)
    typer.echo(f"Generated seed {seed} into {target} in {time.perf_counter()-t0:.2f}s")
    _echo("invoices", str(len(ds.invoices)))
    _echo("gateway settlements", str(len(ds.settlements)))
    _echo("bank transactions", str(len(ds.bank)))


@app.command()
def match(
    data: Path = typer.Option(Path("data/42"), help="Dataset directory."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Deterministic tiers only."),
    offline: bool = typer.Option(False, "--offline", help="Replay the committed cache; no API key."),
    model: str = typer.Option(None, help="Override the escalation model."),
) -> None:
    """Run the reconciliation pipeline."""
    from recon.agent.client import DEFAULT_MODEL
    from recon.pipeline import run_pipeline

    result = run_pipeline(data, use_llm=not no_llm, offline=offline, model=model or DEFAULT_MODEL)
    _report(result, data)


@app.command()
def evaluate(
    data: Path = typer.Option(Path("data/42"), help="Dataset directory."),
    no_llm: bool = typer.Option(False, "--no-llm"),
    offline: bool = typer.Option(True, "--offline/--live", help="Replay the committed cache."),
    model: str = typer.Option(None),
    reports: Path = typer.Option(Path("reports"), help="Where to write the reports."),
) -> None:
    """Score the pipeline against ground truth and write the reports."""
    from recon.agent.client import DEFAULT_MODEL
    from recon.controller.cash_position import build_cash_position
    from recon.controller.ledger import build_ledger
    from recon.eval.metrics import evaluate as score
    from recon.eval.metrics import evaluate_invoices, summarise_llm
    from recon.eval.html_report import write_html_report
    from recon.eval.report import (
        write_cash_position,
        write_exceptions,
        write_gate_rejections,
        write_ledger,
        write_metrics,
    )
    from recon.pipeline import run_pipeline

    chosen = model or DEFAULT_MODEL
    result = run_pipeline(data, use_llm=not no_llm, offline=offline, model=chosen)

    metrics = score(data, result.bank)
    metrics["invoice_level"] = evaluate_invoices(data, result.invoice_matches, result.invoice_residue)
    metrics["timings"] = result.timings
    metrics["llm_stats"] = result.llm_stats
    if result.outcomes:
        metrics["llm"] = summarise_llm(result.outcomes, chosen)

    position = build_cash_position(
        result.sources, result.bank.matches, result.bank.exceptions, result.invoice_matches
    )
    ledger = build_ledger(result.sources, result.bank.matches, result.bank.exceptions)
    metrics["ledger"] = {
        "entries": len(ledger.entries),
        "balances": ledger.balances,
        "total_debits_paise": ledger.total_debits,
        "total_credits_paise": ledger.total_credits,
        "suspense_paise": ledger.suspense_paise,
        "trial_balance": ledger.trial_balance(),
    }

    write_metrics(metrics, reports)
    write_exceptions(result.bank.exceptions, reports)
    write_cash_position(position, reports)
    write_ledger(ledger, metrics["unresolved_value_paise"], reports)
    if result.outcomes:
        write_gate_rejections(result.outcomes, chosen, reports)
    write_html_report(
        metrics, position, result.bank.exceptions, reports / "report.html",
        dataset=f"seed {data.name}", holdout=data.name == "7", book=ledger,
    )

    _report(result, data, metrics)
    typer.echo("")
    typer.echo("THE BOOKS")
    _echo("journal entries", str(len(ledger.entries)))
    _echo("trial balance", "BALANCED" if ledger.balances else "OUT OF BALANCE")
    _echo(
        "suspense ties to exception queue",
        str(abs(ledger.suspense_paise) == metrics["unresolved_value_paise"]),
    )
    typer.echo(
        f"\nWrote {reports}/report.html, metrics.md, metrics.json, "
        f"exceptions.csv, cash_position.md, ledger.md"
    )


@app.command("cash-position")
def cash_position(
    data: Path = typer.Option(Path("data/42")),
    no_llm: bool = typer.Option(False, "--no-llm"),
    offline: bool = typer.Option(True, "--offline/--live"),
) -> None:
    """Show where the money is."""
    from recon.controller.cash_position import build_cash_position
    from recon.eval.report import render_cash_position
    from recon.pipeline import run_pipeline

    result = run_pipeline(data, use_llm=not no_llm, offline=offline)
    position = build_cash_position(
        result.sources, result.bank.matches, result.bank.exceptions, result.invoice_matches
    )
    typer.echo(render_cash_position(position))


@app.command()
def ledger(
    data: Path = typer.Option(Path("data/7")),
    no_llm: bool = typer.Option(False, "--no-llm"),
    offline: bool = typer.Option(True, "--offline/--live"),
) -> None:
    """Post the reconciliation to a double-entry ledger and show the trial balance."""
    from recon.controller.ledger import build_ledger
    from recon.eval.report import render_ledger
    from recon.pipeline import run_pipeline

    result = run_pipeline(data, use_llm=not no_llm, offline=offline)
    book = build_ledger(result.sources, result.bank.matches, result.bank.exceptions)
    typer.echo(render_ledger(book, sum(e.amount_paise for e in result.bank.exceptions)))


@app.command()
def compare(
    data: Path = typer.Option(Path("data/42")),
    models: str = typer.Option(None, help="Comma-separated model ids."),
    offline: bool = typer.Option(True, "--offline/--live"),
) -> None:
    """Run identical escalation packets through several models and grade the gate.

    'Accepted by the gate' and 'actually correct' are reported separately on purpose: the
    gate proves internal consistency, not truth, and conflating them would repeat the very
    mistake the gate exists to prevent.
    """
    from recon.agent.client import COMPARISON_MODEL, DEFAULT_MODEL
    from recon.domain.csvio import read_models
    from recon.domain.models import GroundTruthInvoice
    from recon.pipeline import run_pipeline

    chosen = [m.strip() for m in models.split(",")] if models else [DEFAULT_MODEL, COMPARISON_MODEL]
    truth = {
        g.payment_id: set(g.invoice_ids)
        for g in read_models(data / "ground_truth_invoice.csv", GroundTruthInvoice)
    }

    header = f"  {'model':26}{'proposed':>10}{'accepted':>10}{'rejected':>10}{'correct':>9}{'acc.but wrong':>15}"
    typer.echo("")
    typer.echo(header)
    typer.echo("  " + "-" * (len(header) - 2))
    for model in chosen:
        result = run_pipeline(data, use_llm=True, offline=offline, model=model)
        proposed = [o for o in result.outcomes if o.verdict == "match"]
        accepted = [o for o in result.outcomes if o.accepted]
        rejected = [o for o in proposed if not o.accepted]
        graded = [o for o in accepted if o.level == "invoice"]
        right = [o for o in graded if set(o.proposed) == truth.get(o.target_id, set())]
        typer.echo(
            f"  {model:26}{len(proposed):>10}{len(accepted):>10}{len(rejected):>10}"
            f"{len(right):>9}{len(graded) - len(right):>15}"
        )
        for o in rejected:
            typer.echo(f"      REJECTED {o.target_id}: {o.failure}")
            typer.echo(f"        model said {sorted(o.proposed)} at confidence {o.confidence}")
            typer.echo(f"        {o.reasoning[:150]}")
    typer.echo("")


@app.command()
def demo(seed: int = typer.Option(7), n: int = typer.Option(250)) -> None:
    """Generate, reconcile, and evaluate end to end on the held-out seed.

    Replays the committed model cache, so no API key is needed.
    """
    data = Path("data") / str(seed)
    typer.echo("=" * 72)
    typer.echo(f"  RECONCILIATION DEMO  -  seed {seed}")
    typer.echo("=" * 72)
    generate(seed=seed, n=n, out=data)
    typer.echo("")
    evaluate(data=data, no_llm=False, offline=True, model=None, reports=Path("reports"))


def _report(result, data: Path, metrics: dict | None = None) -> None:
    from recon.eval.metrics import evaluate as score

    m = metrics or score(data, result.bank)
    typer.echo("")
    typer.echo("BANK <-> BATCH")
    _echo("precision (strict set equality)", f"{m['precision_strict']:.2%}")
    _echo("recall (strict)", f"{m['recall_strict']:.2%}")
    _echo("false matches", f"{m['false_matches']} of {m['asserted_matches']} asserted")
    _echo("match rate", f"{m['match_rate']:.2%}")
    _echo("coverage (any verdict)", f"{m['coverage']:.2%}")
    _echo("exceptions", str(m["exceptions"]))

    inv = m.get("invoice_level")
    if inv:
        typer.echo("")
        typer.echo("PAYMENT <-> INVOICE")
        _echo("precision (strict set equality)", f"{inv['precision_strict']:.2%}")
        _echo("matched", f"{inv['matched']} of {inv['payments']}")
        _echo("residue", str(inv["residue"]))

    llm = m.get("llm")
    if llm:
        typer.echo("")
        typer.echo("MODEL ESCALATION")
        _echo("model", llm["model"])
        _echo("items escalated", str(llm["escalated"]))
        _echo("proposed a match", str(llm["proposed_match"]))
        _echo("accepted by verification gate", str(llm["accepted"]))
        _echo("REJECTED by verification gate", str(llm["failed_verification"]))

    t = result.timings
    typer.echo("")
    typer.echo("THROUGHPUT")
    deterministic = t["bank_s"] + t["invoice_s"]
    rows = m["bank_rows"] + (inv["payments"] if inv else 0)
    _echo("deterministic matching", f"{deterministic:.3f}s for {rows} records")
    _echo("records/second (deterministic)", f"{rows/deterministic:,.0f}")
    stats = getattr(result, "llm_stats", {}) or {}
    if stats.get("cache_hits") and not stats.get("calls"):
        _echo("model escalation", f"{t['llm_s']:.2f}s ({stats['cache_hits']} replayed from cache)")
    elif stats:
        _echo(
            "model escalation",
            f"{t['llm_s']:.1f}s ({stats.get('calls', 0)} live calls, "
            f"{stats.get('cache_hits', 0)} cached)",
        )


if __name__ == "__main__":
    app()
