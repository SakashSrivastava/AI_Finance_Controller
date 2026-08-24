# Settlement and statement conventions

This document is the **interface the matcher is written against**. It describes how the
payment gateway settles money and how the bank reports it, in the form a finance team
would hand to an engineer.

It exists for a methodological reason. The same author wrote the data generator and the
matcher, which creates a real risk of the matcher "knowing" the generator's quirks and
scoring well for the wrong reason. The holdout seed only partly guards against that,
because the generator itself is fixed across seeds. So the rule is:

> **The matcher's parsing rules are derived from this document, not from the generator's
> source.** Anything the generator emits that is not described here is something the
> matcher is expected to miss.

The consequence is visible in the metrics: UTR extraction recall is around 85%, not 100%.
A 100% figure would mean this document had been written to match the implementation.

---

## 1. Money

All amounts are integers in **paise**. There are no floats anywhere in the pipeline.
Rupees appear only at display time.

## 2. Fee model

The gateway charges the merchant a platform fee and GST on that fee. Both are rounded to
the nearest paise, **half away from zero** (`ROUND_HALF_UP`), which is Indian financial
convention and is *not* what Python's built-in `round()` does.

| Transaction | Fee | GST | Net effect on the payout |
|---|---|---|---|
| `payment` | 2% of gross | 18% of the fee | `+ (gross − fee − gst)` |
| `refund` | none | none | `− gross` |
| `chargeback` | flat ₹500 | 18% of ₹500 | `− (gross + 500 + 90)` |

**A refund does not return the fee.** The gateway already earned it on the original
capture and keeps it. A model that assumes refunds are symmetric will be wrong by exactly
the original fee on every refunded batch.

A chargeback returns the disputed gross *and* levies a flat penalty on top.

## 3. Settlement timing

- A payment is **captured** on day *D*.
- It is **settled** to the merchant's bank on day *D + 1* or *D + 2*.
- The bank applies a **value date** that is normally the settlement date, but may lag it
  by **1 to 3 days**.

A matcher should therefore search a window of roughly **0 to 3 days before** the bank
value date, and must not assume the settlement date and the value date are equal.

## 4. Batching

Settlement is **many-to-one**. The gateway groups all payments settling on the same day
into one batch, nets the fees, applies any refunds and chargebacks in that batch, and
pays out a **single** amount. The bank statement shows **one credit line for the whole
batch**.

Consequences:

- A bank credit almost never equals any single payment amount.
- The credit equals the **sum of the net amounts** of every settlement sharing that batch,
  including negative rows for refunds and chargebacks.
- Batch sizes observed in practice: 1 to 8 payments, occasionally more once refunds are
  included.

Any approach that assumes 1:1 amount equality fails on the majority of rows.

### 4a. Withheld payments

Not every payment captured under a batch is paid out with it. The gateway withholds some
against a rolling reserve or a risk review, releasing them later. The credit is then a
**strict subset** of the payments sharing that UTR, and the batch total will exceed it.

A matcher that only ever compares whole batch totals will miss these. The shortfall is
not rounding and must not be absorbed as though it were.

### 4b. Combined payouts

The gateway sometimes settles **several whole batches in one credit**, typically when two
batches close on the same day. Both UTRs exist in the settlement report, but the bank
narration carries only one of them — or neither.

So a credit does not necessarily live inside a single batch. The natural unit for this
case is the batch, not the payment: search combinations of whole batch totals rather than
arbitrary cross-batch sets of payments, which cannot occur.

### 4c. Colliding amounts

Two different batches can settle in the same window with an **identical net total**. When
neither narration carries a UTR, there is genuinely nothing in the data that distinguishes
them.

There is no correct answer here, and the correct behaviour is to **refuse both** rather
than pick one. Reporting a match for either is a coin flip dressed up as reconciliation.
This is what an `ambiguous_multiple_subsets` exception is for.

## 5. The UTR

Each batch payout carries a **UTR** (Unique Transaction Reference). Format:

```
AAAAN00000000000
^^^^                4-letter bank code (HDFC, ICIC, UTIB, SBIN, KKBK, ...)
    ^               literal N
     ^^^^^^^^^^^    11 digits
```

Total length 16 characters, uppercase.

The UTR is the strongest available join key: when a narration carries a full UTR **and**
the batch total agrees with the credit, the match is certain.

## 6. Bank narration

`narration` is a free-text field written by the bank, not by the gateway. It is
inconsistent by nature. Known characteristics:

**Delimiters vary.** The UTR may be surrounded by `-`, `/`, `*`, `:`, spaces, or nothing.

**Position varies.** Some formats lead with the reference; others lead with the merchant
name and put the reference at the end.

**Prefixes vary** by payment rail: `NEFT`, `IMPS`, `UPI`, `RTGS`, `ACH`, `CMS`, `MB`,
`TRF`, `BY TRANSFER`.

Representative shapes (this list is **not exhaustive** — treat it as examples of the
families above, not as a closed set):

```
NEFT-<UTR>-RAZORPAY SOFTWARE PVT LTD
IMPS/<UTR>/RAZORPAYSOFT
UPI-RAZORPAY-<UTR>
RTGS <UTR> RAZORPAY
CMS/<UTR>
MERCHANT PAYOUT RAZORPAY SOFTWARE PVT LTD UTR <UTR>
```

**Some narrations carry no UTR at all.** Roughly 12% of settlement credits arrive with
only a generic description such as `RAZORPAY SETTLEMENT CREDIT`. These can only be
matched on amount and date window.

**Narration fields are length-capped by the exporting system**, typically around 40
characters. When the reference sits at the end of a long narration, the cap truncates it,
leaving a partial UTR or none at all. A truncated reference must not be treated as a
match — a prefix is a hint, not a join key.

Combining the last two points: **only about 85% of settlement credits carry a fully
recoverable UTR.** The remainder must be resolved by amount and date, or escalated.

## 7. Refunds and chargebacks in a batch

Refunds and chargebacks appear as settlement rows with **negative net amounts** sharing
the batch's UTR. They reduce the payout.

For subset-search purposes they must **not** be treated as freely selectable candidates.
A refund only ever attaches to a batch that already contains the payment it reverses;
allowing negative amounts into an unconstrained subset search both breaks the standard
pruning rules and invents combinations that cannot occur.

## 8. Duplicate postings

Banks occasionally post a credit, reverse it with a matching debit, and repost it. The
statement then shows **three rows** for **one** economic event:

```
day D      credit  ₹X    original posting
day D+1    debit   ₹X    reversal
day D+1/2  credit  ₹X    repost
```

All three rows carry the same amount, and the credits normally carry the same UTR. The
reversal narration typically contains a reversal keyword — `REV`, `REVERSAL`, or
`RETURN OF`.

**Attribution convention:** the payments belong to the **repost** — the credit that
survives in the closing balance. The original and the reversal carry no payments.

Because all three rows share one UTR, this collapse must happen **before** any UTR-based
matching. Otherwise the earliest credit consumes the batch and the repost — the row that
should hold it — is left unmatched.

A matcher that asserts the same payment set against all three rows has tripled the money.
Detecting the triple and collapsing it to one event is required, not optional.

## 9. Debits

A debit is never a settlement payout. Every debit is one of:

1. **A reversal** of an earlier credit — part of a duplicate-posting group (§8).
2. **A chargeback debited directly** rather than netted into a batch.
3. **An ordinary business outflow** — vendor payment, salary run, GST challan, rent,
   bank charges. These are **out of scope** for settlement reconciliation and should be
   labelled as such, not left sitting in the exception queue as unexplained.

## 10. Invoice references

The `invoice_ref` on a settlement is transcribed from what the customer typed, so it is
unreliable. Observed problems:

- **Exact** (about 88% of payments) — `INV-2026-01234`
- **Garbled** — character confusion (`I`/`1`, `O`/`0`, `S`/`5`), lost or changed
  separators, truncation, case changes, stray prefixes or suffixes such as `#` or `/PART`
- **Multiple** — one payment covering several invoices carries a comma-separated list
- **Partial** — one invoice settled by two or more payments, each carrying the same ref

Reference repair is a **semantic** problem, not an arithmetic one. It is the natural place
for a language model, and the natural place for fuzzy string matching — unlike batch
totals, which code should decide.

## 11. Credits with no gateway counterpart

Some credits are customers paying the merchant **directly** by NEFT/RTGS/IMPS, bypassing
the gateway entirely. There is no settlement record because no settlement occurred.

These are **genuinely unresolvable** from the three available sources. They belong in the
exception report, correctly identified. A system that reports them as matched is
fabricating a reconciliation.

---

## Reconciliation happens at two levels

These are different questions and conflating them is a category error:

| Level | Question | Cardinality |
|---|---|---|
| Bank ↔ batch | Which payments make up this bank credit? | one credit ↔ many payments |
| Payment ↔ invoice | Which invoices does this payment settle? | many ↔ many |

"Partial payment" is a property of the **invoice** link, not the bank link. A bank credit
cannot meaningfully be labelled a partial payment.
