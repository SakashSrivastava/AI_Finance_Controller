# Multi-source reconciliation agent

Razorpay AI Buildathon — **Track 04, AI Finance Controller**

Reconciles three financial sources for a merchant — invoices, payment-gateway settlements,
and a bank statement — reports measured accuracy against known ground truth, and produces
an honest list of the exceptions it could not resolve.

Matching is **many-to-one**: the gateway batches payments, nets fees and GST, subtracts
refunds and chargebacks, withholds some payments, and pays out a single amount that the
bank posts days later under a mangled narration. Any approach assuming 1:1 amount
equality fails on most rows.

## In one screen

| | |
|---|---|
| **Precision** (strict set equality) | **100.00%** — 0 false matches in 232 assertions |
| **Recall** | 92.06% — the gap is 18 rows it *correctly refuses to guess* |
| Invoices matched | **1,343 of 1,343** |
| Throughput | 1,634 records in ~0.02s, deterministic path |
| Books | 291 journal entries, trial balance balanced, suspense ties to the exception queue |
| Reproduce | `recon demo` — offline, no API key, ~1 second |
| Tests | 129 |

Numbers are from **seed 7, generated after the matcher was frozen**. Tuning was on seed 42.

**The finding worth your 60 seconds:** the agent has a tool to check its own arithmetic. It
used it on 8 of 8 proposals the gate later refused, and its own check was *correct* — yet
4 of those 8 were wrong. It verified that its answer closes; what mattered was whether
*only* its answer closes. [Jump to the detail](#3-giving-the-agent-a-verification-tool-did-not-solve-verification).

---

## Results

**Tuning was done on seed 42. Every number below is from seed 7, which was generated
after the matcher was finished and never used to tune anything.**

### Headline — full system, held-out seed 7

| | Bank ↔ batch | Payment ↔ invoice |
|---|---|---|
| **Precision (strict set equality)** | **100.00%** | **100.00%** |
| **False matches** | **0** of 232 asserted | **0** of 1,343 |
| Recall (strict) | 92.06% | — |
| Matched | 232 of 291 rows | **1,343 of 1,343** |
| Coverage | 90.72% | 100% |
| Match rate | 79.73% | 100% |
| Unresolved | 27 exceptions | 0 |
| Value under investigation | ₹1,23,68,489.74 | |

Match rate is the share of bank rows carrying an asserted match. It is reported **after**
precision on purpose: a system that matches everything wrongly scores 100% on it. Coverage
(90.72%) is higher because it also counts rows the system *explained* without asserting
money against them — a reversal leg, an out-of-scope debit.

Precision is stated before match rate everywhere in this project, because **a wrong match
on money is worse than no match.** Agreement is *strict set equality*: a match is a set of
ids, and getting four of five right in a batch is a wrong answer, because the money does
not reconcile. Mean Jaccard is 1.000 — there are no near misses, only refusals.

### Deterministic vs escalated

The tiers are run twice, once with the model layer disabled, so its marginal contribution
is measured rather than assumed:

| | Deterministic only | With model escalation | Lift |
|---|---|---|---|
| Bank precision | 100.00% | 100.00% | — |
| Bank recall | 91.67% | 92.06% | +1 match |
| Bank exceptions | 28 | 27 | −1 |
| Invoice matched | 1,330 / 1,343 | **1,343 / 1,343** | **+13** |
| Invoice precision | 100.00% | 100.00% | — |
| Value under investigation | ₹1,32,07,474.61 | ₹1,23,68,489.74 | −₹8.4L |

**The model's contribution is small and entirely semantic**: thirteen mangled invoice
references the deterministic tiers refused, plus one compound bank case
(`combined_payout` + `settlement_hold`) that no single tier covers. It resolved zero of
the arithmetic problems, because code had already searched those exhaustively. That is the
honest result and it is the empirical form of the track's own claim — generation was never
the bottleneck.

### Throughput

| Metric | Value |
|---|---|
| Deterministic matching | 1,634 records in ~0.02–0.08s |
| Records/second | **20,000 – 87,000** (varies with machine load) |
| Model calls | 41 per model, cached and replayable offline |
| Cost | ₹0 — Groq free tier |

The deterministic path is milliseconds. The escalation path takes tens of minutes of wall
clock on a rate-limited free tier for 41 calls. Those are different regimes and reporting
one number for both would be misleading.

### Why recall is 92% and not higher

The gap is almost entirely one case type, and the system is **behaving correctly** on it:

| Case type | Rows | Asserted | Precision | Matchable | Recall |
|---|---|---|---|---|---|
| `amount_collision` | 18 | **0** | — | 18 | **0.00%** |
| `missing_utr` | 64 | 38 | 100.00% | 56 | 67.86% |
| `rounding_drift` | 5 | 4 | 100.00% | 5 | 80.00% |
| `combined_payout` | 21 | 19 | 100.00% | 21 | 90.48% |
| `refund_in_batch` | 17 | 14 | 100.00% | 15 | 93.33% |
| `settlement_hold` | 19 | 18 | 100.00% | 19 | 94.74% |
| `clean_batch` | 99 | 99 | 100.00% | 99 | 100.00% |
| `timing_gap` | 40 | 38 | 100.00% | 38 | 100.00% |
| `truncated_narration` | 17 | 17 | 100.00% | 17 | 100.00% |
| `chargeback_in_batch` | 8 | 8 | 100.00% | 8 | 100.00% |
| `dup_repost` | 11 | 11 | 100.00% | 11 | 100.00% |

An **amount collision** is two batches settling in the same window with an identical net
total, where neither bank narration carries a UTR. Nothing in the data distinguishes them.
The system asserts nothing on all 18 and files them as `ambiguous_multiple_subsets`.
Guessing would have lifted recall to roughly 98% and produced about nine false matches on
real money. Refusing is the correct answer, and it is why recall is reported second.

The `missing_utr` line is the same story counted differently. Every collision is also a
missing-UTR row, so 18 of its 56 matchable rows *are* the collisions. The other 38 are all
matched, correctly, with no UTR to go on — which is exactly 67.86%. Once the collisions are
set aside, amount-and-date matching resolves every remaining UTR-less credit.

The remaining exceptions are **genuinely unresolvable**: direct NEFT credits from customers
who bypassed the gateway, so no settlement record exists at all. A system reporting 100%
coverage on this data would be lying. Every exception carries a specific reason code and
the action a human should take, in `reports/seed7/exceptions.csv`.

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
recon ledger --data data/7             # the books: journal entries and trial balance
pytest -q                              # 100 tests
```

Outputs land in `reports/`: `report.html` (self-contained, no server), `metrics.md`,
`metrics.json`, `exceptions.csv`, `cash_position.md`, `ledger.md`. The published run is
committed under `reports/seed7/` so the numbers can be read without running anything.

To run live instead of from cache, put a [Groq](https://console.groq.com/keys) key in
`.env` (see `.env.example`) and pass `--live`.

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

### Is this an agent?

Worth answering directly, because "agent" usually means something more autonomous than
this.

It **is** an agent in the sense that matters here. It takes in three unlabelled sources,
decides for itself which strategy applies to each row, chooses when a case is beyond
deterministic reasoning and escalates it, assembles its own evidence packet, forms a
proposal, **checks its own work against the source data**, and stops — either asserting,
or declining and saying why. Perceive, decide, act, verify, abstain, with a stopping rule.
It runs unattended over a batch and produces a decision and a justification for every row.

It is deliberately **not** a free-roaming tool-using loop that decides its own next action
each turn. That would be the wrong shape for this problem. Money movement wants bounded
autonomy: a fixed decision procedure, a known escalation path, an arithmetic gate the
model cannot argue past, and an audit trail for every proposal including the refused ones.
An agent that can talk itself into a transfer is a liability, and the track's own premise —
that verification is the bottleneck — is the reason why.

So the autonomy is spent on judgement, and withheld from execution. That is a design
decision, and the rejected proposals in `audit/llm_calls.jsonl` are the evidence it was
the right one.

### Running the books

Reconciliation says whether rows agree. The cash position says where the money is. Neither
is bookkeeping, so the reconciliation also **posts to a double-entry ledger** — one
balanced journal entry per bank transaction, with receivables credited gross and the
gateway fee and its GST debited explicitly. The merchant never sees that fee as a payment;
it is netted before the money arrives, so reconstructing it is the only way it reaches the
books at all, and the GST is a real input credit.

Two invariants make the ledger a second opinion rather than a rendering:

| Check | Result |
|---|---|
| Every journal entry balances, and so does the ledger | ✅ 291 entries, ₹14,30,15,765.92 both sides |
| Suspense balance == exception queue value | ✅ ₹1,23,68,489.74 both routes |

Double entry is arithmetic over the whole reconciliation that never consults the matcher's
logic, so a mis-attribution that moved amounts would stop the trial balance closing. It
found something the moment it was switched on: four `rounding_drift` batches could not
balance, because the bank credited a few paise away from the batch total. Real books post
that to a rounding difference rather than absorbing it — so now these do too.

The suspense tie-out is the same idea from the other side. The exception queue is produced
by the matcher; the suspense balance falls out of bookkeeping over every bank row. Two
independent routes, one number, asserted by a test.

```bash
recon ledger --data data/7
```

Full detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The settlement and statement
conventions the matcher was written against: [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md).

---

## Three findings

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

### 2. A model cannot verify its own uniqueness claim

The gate originally checked that a proposal's amounts *sum to the credit*. That turns out
to be too weak. If two different subsets both reconcile, accepting either is a coin flip,
and the one that happens to match ground truth is luck, not verification. So the gate now
re-searches the same shortlist the model was shown and refuses anything not **uniquely**
determined.

Escalating the holdout residue to `gpt-oss-20b` produced these two. They are best read as
a pair. All seven refused proposals, with the model's own words beside the arithmetic that
refuted them, are committed in
[`reports/seed7/gate_rejections.openai-gpt-oss-20b.md`](reports/seed7/gate_rejections.openai-gpt-oss-20b.md) — and reproduce with
`recon compare --data data/7`, no API key required.

**`bank_000005`** — ₹5,89,296.64

> **Model, confidence 0.95:** *"The bank credit of 58,929,664 paise matches exactly the net
> amount of settlement pay_001343. **No other combination of the listed settlements sums to
> this amount**, so the credit is attributable to that single settlement."*
>
> **Gate:** `REJECTED — another_subset_also_reconciles` · `subsets_that_reconcile: 2`
>
> **Ground truth:** four entirely different payments. **The model was wrong.**

**`bank_000134`** — ₹3,01,971.26

> **Model, confidence 0.92:** *"…**Although another subset of three settlements also sums to
> the same amount**, the presence of a single settlement matching the credit and the
> possibility that the other three were withheld… makes pay_001007 the most plausible
> match."*
>
> **Gate:** `REJECTED — another_subset_also_reconciles` · `subsets_that_reconcile: 2`
>
> **Ground truth:** `pay_001007`. **The model was right.**

In the first, the model asserted uniqueness and was factually wrong about it. In the
second, it *noticed* the ambiguity, reasoned about it sensibly, and reached the correct
answer. **The gate refused both, identically** — because from the available data there is
no way to tell those two situations apart.

So the gate cost a correct match. That is the honest price of the policy, and it is worth
stating plainly rather than hiding: refusing `bank_000134` lost one true positive, but
accepting it on the same evidence would have meant accepting `bank_000005`, which moves
money to the wrong place. Given a wrong match on money is worse than no match, that is the
right trade — but it is a trade, not a free lunch.

### 3. Giving the agent a verification tool did not solve verification

The escalation layer is a real agent loop: read-only tools, the model choosing which to
call and when to stop, `submit` as the only terminal action. One of those tools is
`test_combination`, which sums a proposed set and reports whether it closes against the
bank credit. The agent can check its own arithmetic before committing — exactly what a
human reconciler does.

It used it. On **8 of 8** refused proposals, the agent had run `test_combination` on
precisely the set it went on to submit, and its own check had come back `closes: true`.
The check was correct. It then submitted at 0.90–0.99 confidence.

The gate refused all eight, every one for `another_subset_also_reconciles`.

| Of the 8 self-verified proposals the gate refused | |
|---|---|
| Would have been **correct** | **4** |
| Would have been **wrong** | **4** |

A coin flip, measured. Two of those rows make it concrete — they are the two halves of one
amount collision:

| | agent submitted | ground truth | |
|---|---|---|---|
| `bank_000087` | `pay_000905` | nine other payments | **wrong** |
| `bank_000088` | `pay_000905` | `pay_000905` | **right** |

Same answer, same confidence, same successful self-check, opposite outcomes — because both
sets close against both credits, and nothing in the data says which belongs to which.

**The agent verified the wrong property.** It confirmed *this combination closes*. What
had to be true was *only this combination closes*. That second question is not one a
proposer can answer about itself — it requires searching the space you did not propose,
which is the definition of an independent check.

So refusing those eight cost four true positives and prevented four false matches on real
money. Given a wrong match is worse than no match, that is the right trade — and it is a
trade, not a free lunch.

This is the sharpest form of the track's premise. Generation was not the bottleneck. Nor
was self-verification, which the agent performed correctly and which was not enough.

> **Caveat, stated plainly.** This agentic pass covers 21 of 41 escalations. Groq's free
> tier caps 200,000 tokens per model per day and an agent loop resends its whole
> conversation each turn, so the run exhausted the daily budget partway. The finding above
> concerns the *nature* of the failure and holds on the completed items; the headline
> results in this README come from the completed single-shot runs, not from this one.
> Reproduce with `recon compare --data data/7 --models openai/gpt-oss-20b --agentic`.
> Every refused proposal, with the agent's own reasoning and whether it had verified
> itself, is committed in
> [`reports/seed7/gate_rejections.openai-gpt-oss-20b-agentic.md`](reports/seed7/gate_rejections.openai-gpt-oss-20b-agentic.md).

### Model comparison

The same 41 escalations, two models, identical packets, held-out seed:

| Model | Proposed | Accepted by gate | **Rejected by gate** | Correct | Accepted but wrong | Provider failures |
|---|---|---|---|---|---|---|
| `gpt-oss-120b` | 14 | 14 | **0** | 13 | **0** | 2 |
| `gpt-oss-20b` | 20 | 13 | **7** | 13 | **0** | 9 |

Both models correctly declined the bank-level exceptions that have no gateway counterpart,
rather than inventing one. The smaller model was not less *honest* — it was more *eager*:
it proposed six more matches, seven of which the gate refused, and it failed to emit a
valid document at all nine times out of forty-one.

Neither model produced an accepted-but-wrong match. That is the number that matters, and
it is zero for both.

The load-bearing observation is that **nothing in either model's output distinguishes the
two.** Both are fluent, schema-valid and confident; the 20b's confidence on its seven
refused proposals averaged over 0.9. The difference is only visible because something
outside the model re-derived the arithmetic. That is the argument for the gate, and it is
why "accepted by the gate" is reported separately from "actually correct" above — the gate
proves consistency and uniqueness, not truth, and conflating those would be the same
mistake in a different coat.

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
  a synthetic batch whose difficulty this project chose. The per-case-type table in
  `reports/seed7/metrics.md` shows where the difficulty actually was — and it is worth reading
  the 91.67% recall next to it, because the two numbers trade against each other. This
  system is tuned to refuse rather than guess; a system tuned the other way would report a
  better match rate and move money to the wrong place.
- **The 8% recall gap is a deliberate refusal, not a bug** — but it is also a real
  limitation. A production system would resolve most `amount_collision` rows by pulling the
  gateway's own payout report for the UTR, which is a data source this project does not
  have. The right fix is more evidence, not cleverer matching.
- **The model's measured contribution is small in absolute terms** — it resolves the
  handful of references deterministic tiers refuse. That is the honest result, and it is
  the empirical form of the track's own claim: generation was never the bottleneck.
- **Escalation is not free.** Groq's free tier throttles to a few thousand tokens per
  minute, so the full escalation pass takes tens of minutes of wall clock even though the
  deterministic pass takes 80 milliseconds. The committed cache means you pay that once.

---

## Tests

100 tests, all green, running in about a second.

The ones worth reading: `tests/test_verification_gate.py` feeds the gate confident,
schema-valid, entirely fabricated verdicts and asserts the money does not move.
`tests/test_escalation.py` runs the whole pipeline against a model that lies on every
single escalated item and asserts that not one asserted match changes.
`tests/test_generator_consistency.py` proves the ground truth is internally correct —
without it, every metric here would be unfalsifiable.
