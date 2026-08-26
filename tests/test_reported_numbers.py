"""The README must not drift from the code.

Every number quoted in the README is re-derived here from the committed reports. This has
already caught stale figures twice during development - the dataset got harder, the
metrics moved, and prose written against the old run survived. A public repository whose
headline numbers disagree with its own output is worse than one with no numbers at all.

If a figure here fails, the fix is to re-run `recon evaluate --data data/7 --offline
--reports reports/seed7` and update the prose, not to relax the assertion.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

README = Path("README.md")
METRICS = Path("reports/seed7/metrics.json")


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def metrics() -> dict:
    return json.loads(METRICS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def headline(readme: str) -> str:
    """Just the headline table.

    Scoping matters: a figure like 92.06% also appears in the ablation table lower down,
    so searching the whole document would let a wrong headline slip through unnoticed.
    """
    start = readme.index("### Headline")
    end = readme.index("###", start + 10)
    return readme[start:end]


def test_committed_metrics_exist(metrics):
    """The published run is committed so the numbers are readable without running anything."""
    assert metrics["bank_rows"] > 0
    assert "invoice_level" in metrics
    assert "ledger" in metrics


@pytest.mark.parametrize(
    "label, key, fmt",
    [
        ("precision", "precision_strict", lambda v: f"{v:.2%}"),
        ("recall", "recall_strict", lambda v: f"{v:.2%}"),
        ("match rate", "match_rate", lambda v: f"{v:.2%}"),
        ("coverage", "coverage", lambda v: f"{v:.2%}"),
    ],
)
def test_headline_percentages_appear_verbatim(headline, metrics, label, key, fmt):
    value = fmt(metrics[key])
    assert value in headline, (
        f"{label} is {value} in metrics.json but the README headline table does not say so"
    )


def test_counts_appear_verbatim(headline, metrics):
    for label, value in [
        ("asserted matches", metrics["asserted_matches"]),
        ("bank rows", metrics["bank_rows"]),
        ("exceptions", metrics["exceptions"]),
        ("payments", metrics["invoice_level"]["payments"]),
    ]:
        assert f"{value:,}" in headline or str(value) in headline, (
            f"{label} ({value}) not in the README headline table"
        )


def test_zero_false_matches_is_actually_true(readme, metrics):
    """The strongest claim in the README, so it gets its own check."""
    assert metrics["false_matches"] == 0
    assert metrics["false_matches_on_unresolvable"] == 0
    assert "0 false matches" in readme.lower() or "**0**" in readme


def test_ledger_claims_hold(readme, metrics):
    ledger = metrics["ledger"]
    assert ledger["balances"] is True
    assert ledger["total_debits_paise"] == ledger["total_credits_paise"]
    assert abs(ledger["suspense_paise"]) == metrics["unresolved_value_paise"], (
        "the README claims suspense ties to the exception queue to the paise"
    )


def test_no_stale_seed_42_headline(readme):
    """Tuning was on seed 42; every reported number must come from the holdout."""
    assert "unseen seed 7" in readme or "held-out seed 7" in readme or "seed 7" in readme
    body = readme.split("## Honest limitations")[0]
    for claim in re.findall(r"from seed 42", body):
        pytest.fail("README body claims a number is from seed 42, which is the tuning seed")


def test_every_relative_link_resolves(readme):
    """A README that cites evidence it does not ship is not citing evidence."""
    broken = []
    for text, target in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", readme):
        if target.startswith(("http://", "https://", "#")):
            continue
        if not Path(target.split("#")[0]).exists():
            broken.append(f"{text} -> {target}")
    assert not broken, f"README links to files that do not exist: {broken}"
