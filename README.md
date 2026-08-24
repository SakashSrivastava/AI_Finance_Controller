# Multi-source reconciliation agent

Razorpay AI Buildathon — **Track 04, AI Finance Controller**

Reconciles three financial sources for a merchant — invoices, payment-gateway settlements,
and a bank statement — reports measured accuracy against known ground truth, and produces
an honest list of the exceptions it could not resolve.

Matching is **many-to-one**: the gateway batches payments, nets fees and GST, subtracts
refunds and chargebacks, withholds some payments, and pays out a single amount that the
bank posts days later under a mangled narration. Any approach assuming 1:1 amount
equality fails on most rows.

---

## Results

**Tuning was done on seed 42. Every number below is from seed 7, which was generated
after the matcher was finished and never used to tune anything.**

### Bank ↔ batch

| Metric | Value |
|---|---|
| **Precision (strict set equality)** | **100.00%** |
| Recall (strict) | 100.00% |
| Mean Jaccard overlap | 1.000 |
| **False matches** | **0 of 239 asserted** |
| False matches on unresolvable rows | 0 |
| Coverage | 95.86% |
| Exceptions | 11 |

### Payment ↔ invoice

| Metric | Value |
|---|---|
| **Precision (strict set equality)** | **100.00%** |
| Matched | 1,228 of 1,235 payments (deterministic only) |
| Residue escalated to the model | 7 |

### Throughput

| Metric | Value |
|---|---|
| Deterministic matching | 1,501 records in 0.021s |
| Records/second | **73,047** |
| Model calls | 21 (cached; replayable offline) |
| Cost | ₹0 — Groq free tier |

Precision is stated before match rate everywhere in this project, because **a wrong match
on money is worse than no match.** Agreement is *strict set equality*: a match is a set of
payment ids, and getting four of five right in a batch is a wrong answer, because the
money does not reconcile. Mean Jaccard is reported alongside so near misses can be
distinguished from wild guesses.

The 11 remaining exceptions are **genuinely unresolvable**: direct NEFT credits from
customers that bypassed the gateway entirely, so no settlement record exists. A system
reporting 100% coverage on this data would be lying. They are listed, with reasons, in
`reports/exceptions.csv`.

---

## The design

**Deterministic code decides. The model only proposes.**

No monetary match is ever asserted on a model output alone. Every proposal is re-derived
arithmetically from the source data before it becomes an assertion — the ids must exist,
must not already be attributed, must fall inside the settlement window, and their net
amounts must sum to the credit. If any check fails the item becomes `needs_human`. It is
never repaired, retried, or quietly accepted at lower confidence.

The track's premise is that *verification capacity, not generation speed, is the
bottleneck*. This repository is built as an argument for that claim rather than a project
that happens to call an LLM.

### Division of labour

| | Handled by | Why |
|---|---|---|
| Summing subsets, closing batches, fee arithmetic | **code** | strictly better at it, and exhaustive |
| Reading `00423`, `INVOICE-2026-00745`, transposed digits | **model** | genuinely beats a regex and a fuzzy ratio |
| Deciding whether anything moves | **the gate** | neither of the above gets a vote |

The model is never asked to do arithmetic. Structured outputs are enforced provider-side
by a strict JSON schema, so a malformed reply is impossible — which says nothing about
whether the content is *right*, which is exactly what the gate is for.

Full detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The settlement and statement
conventions the matcher was written against: [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md).

---

## Two findings

### 1. A well-formed key is not a correct key

This one came from the deterministic layer, not the LLM.

Three payments were being matched at **confidence 1.0 to the wrong invoice**. Transposing
two digits of `INV-2026-00110` produces `INV-2026-01010` — which *exists* in the ledger,
under a different customer. Exact string matching does not fail on a corrupted key like
that. It succeeds, confidently, on the wrong money.

No amount of string cleverness fixes it, because the key is well-formed. Only corroborating
a second independent field does. And when that rule was applied to the exact-match tier
alone, precision did not move at all — the case simply fell through and the *canonical*
tier made the identical wrong match. The rule had to hold at every lookup or it held
nowhere.

### 2. The model noticed the arithmetic failed, and argued its way past it

Escalating the same residue to `gpt-oss-20b` produced this, verbatim from
`audit/llm_calls.jsonl`:

> **Payment** `pay_000886` — Bharat Tyre Traders, ₹2,92,627.72, reference `'00852'`
>
> **Model, confidence 0.90:** *"The reference string `00852` matches the numeric suffix of
> invoice INV-2026-00852. The payment amount (29,262,772 paise) **exceeds** the amount of
> this invoice (18,875,144 paise), **which is permissible because a payment can cover
> multiple invoices**…"*
>
> **Gate:** `REJECTED — payment_exceeds_invoiced_total` (29,262,772 > 18,875,144)
>
> **Ground truth:** `INV-2026-00851` **and** `INV-2026-00852`

The model saw that the numbers did not work, retrieved a rule that is genuinely true — a
payment *can* cover several invoices — and used it to excuse the discrepancy while citing
only one invoice. It was half right: `00852` really is one of the two. A partial-credit
metric would have rewarded that. Strict set equality and an arithmetic check both refused
it, knowing nothing about ground truth.

This is what "verification capacity, not generation speed" looks like in a single row.

### Model comparison

The same 21 escalations, two models, identical packets:

| Model | Proposed | Accepted by gate | **Rejected by gate** | Correct | Accepted but wrong |
|---|---|---|---|---|---|
| `gpt-oss-120b` | 9 | 9 | 0 | 9 | **0** |
| `gpt-oss-20b` | 7 | 6 | **1** | 6 | **0** |

Both models correctly declined all 12 bank-level exceptions rather than inventing
counterparts for credits that have none. The smaller model was not less *honest* — it was
less *capable*: it resolved three fewer references, failed once to emit valid JSON at all,
and produced the one proposal that failed verification.

The load-bearing observation is that **nothing in either model's output distinguishes the
two.** Both were fluent, schema-valid and confident. The 9-versus-6 gap and the one bad
proposal are only visible because something outside the model re-derived the arithmetic.
That is the argument for the gate, and it is why "accepted by the gate" is reported
separately from "actually correct" above — the gate proves internal consistency, not truth,
and conflating those would be the same mistake in a different coat.

---

## Running it

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -e ".[dev]"
recon demo
```

`recon demo` generates, reconciles, and evaluates end to end in under two minutes, replaying
the committed model cache — **no API key required.**

```bash
recon generate --seed 42 --n 250      # byte-identical for a given seed
recon match --data data/42 --no-llm   # deterministic tiers only
recon match --data data/42 --offline  # replay the committed cache
recon evaluate --data data/7          # score against ground truth, write reports
recon cash-position --data data/7      # where the money is
pytest -q                              # 100 tests
```

Outputs land in `reports/`: `report.html` (self-contained, no server), `metrics.md`,
`metrics.json`, `exceptions.csv`, `cash_position.md`.

To run live instead of from cache, put a [Groq](https://console.groq.com/keys) key in
`.env` (see `.env.example`) and pass `--live`.

---

## Reproducibility

- **Data** — `--seed` produces byte-identical output. Row order is sorted explicitly, and
  CSVs are written with `\n` endings regardless of platform.
- **Search** — subset search uses a deterministic **node budget**, not a wall-clock
  timeout. A timeout would make the same seed produce different headline numbers on a
  loaded laptop.
- **Model** — responses are cached by SHA-256 of the exact request, and **the cache is
  committed to this repository**. Clone it and `recon evaluate --data data/7` reproduces
  the numbers above with no key and no network.
- **Evaluation** — ground truth is read only inside `src/recon/eval/`, enforced by a test
  that scans the import graph of every other package.

---

## Honest limitations

- **The data is synthetic.** It is generated to a documented model of how Indian payment
  settlement behaves, not sampled from a real merchant.
- **The generator and the matcher share an author**, which risks the matcher "knowing" the
  generator's quirks. Two controls: the matcher's parsing rules were written against
  [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) rather than the generator source, and all
  reported numbers come from a seed generated after the matcher was frozen. The control is
  visible in the metrics — UTR extraction is **84.6% available**, not 100%, because capped
  narrations genuinely destroy references the matcher then has to work around.
- **The fee model is simplified**: one flat 2% rate plus 18% GST. Real merchants have
  per-method rates, volume slabs, and negotiated pricing.
- **Not modelled**: multi-currency, TDS, settlement holds beyond a simple withhold,
  reserve release schedules, international settlement lag, or partial reversals.
- **100% precision is not a claim about reconciliation in general.** It is a measurement on
  a 250-transaction synthetic batch whose difficulty this project chose. The per-case-type
  table in `reports/metrics.md` shows where the difficulty actually was.
- **The model's measured contribution is small in absolute terms** — it resolves the
  handful of references deterministic tiers refuse. That is the honest result, and it is
  the empirical form of the track's own claim: generation was never the bottleneck.

---

## Tests

100 tests, all green, running in about a second.

The ones worth reading: `tests/test_verification_gate.py` feeds the gate confident,
schema-valid, entirely fabricated verdicts and asserts the money does not move.
`tests/test_escalation.py` runs the whole pipeline against a model that lies on every
single escalated item and asserts that not one asserted match changes.
`tests/test_generator_consistency.py` proves the ground truth is internally correct —
without it, every metric here would be unfalsifiable.
