# Reconciliation results

## Headline

| Metric | Value |
|---|---|
| **Precision (strict set equality)** | **100.00%** |
| Recall (strict) | 100.00% |
| Mean Jaccard overlap | 1.000 |
| False matches | 0 of 239 asserted |
| False matches on unresolvable rows | 0 |
| Coverage | 95.86% |
| Bank rows | 266 |
| Exceptions | 11 |
| Value under investigation | ₹11,96,464.48 |

Agreement is **strict set equality**: a match is a set of payment ids, and getting four of five right is a wrong answer because the money does not reconcile. Mean Jaccard is reported alongside so near misses can be told apart from wild guesses.

## UTR extraction

- Parser recall (UTR present in narration): **100.00%** (210/210)
- UTR available at all (after missing and capped narrations): **87.87%** of 239 settlement credits

The second number is the ceiling on UTR matching and therefore the size of the job left to the amount-based tiers.

## Resolution by tier

| Tier | Rows |
|---|---|
| `tier0_dup_original` | 3 |
| `tier0_dup_reversal` | 3 |
| `tier0_out_of_scope_debit` | 10 |
| `tier1_utr_exact` | 186 |
| `tier2_batch_sum_window` | 28 |
| `tier3_subset_sum` | 18 |
| `tier4_tolerance` | 7 |

## Exceptions by reason

| Reason | Rows |
|---|---|
| `no_gateway_counterpart` | 11 |

## Per case type

Where the system is strong and where it is not.

| Case type | Rows | Asserted | Precision | Matchable | Recall |
|---|---|---|---|---|---|
| `chargeback_in_batch` | 11 | 11 | 100.00% | 11 | 100.00% |
| `clean_batch` | 125 | 125 | 100.00% | 125 | 100.00% |
| `dup_original` | 3 | 0 | 0.00% | 0 | 0.00% |
| `dup_repost` | 3 | 3 | 100.00% | 3 | 100.00% |
| `dup_reversal` | 3 | 0 | 0.00% | 0 | 0.00% |
| `duplicate_posting` | 9 | 3 | 100.00% | 3 | 100.00% |
| `missing_utr` | 20 | 20 | 100.00% | 20 | 100.00% |
| `out_of_scope_debit` | 10 | 0 | 0.00% | 0 | 0.00% |
| `refund_in_batch` | 15 | 15 | 100.00% | 15 | 100.00% |
| `rounding_drift` | 7 | 7 | 100.00% | 7 | 100.00% |
| `settlement_hold` | 20 | 18 | 100.00% | 18 | 100.00% |
| `timing_gap` | 43 | 41 | 100.00% | 41 | 100.00% |
| `truncated_narration` | 24 | 22 | 100.00% | 22 | 100.00% |
| `unresolvable` | 11 | 0 | 0.00% | 0 | 0.00% |
