# Reconciliation results

## Headline

| Metric | Value |
|---|---|
| **Precision (strict set equality)** | **100.00%** |
| Recall (strict) | 91.67% |
| Mean Jaccard overlap | 1.000 |
| False matches | 0 of 231 asserted |
| False matches on unresolvable rows | 0 |
| Coverage | 90.38% |
| Bank rows | 291 |
| Exceptions | 28 |
| Value under investigation | ₹1,32,07,474.61 |

Agreement is **strict set equality**: a match is a set of payment ids, and getting four of five right is a wrong answer because the money does not reconcile. Mean Jaccard is reported alongside so near misses can be told apart from wild guesses.

## UTR extraction

- Parser recall (UTR present in narration): **100.00%** (190/190)
- UTR available at all (after missing and capped narrations): **75.40%** of 252 settlement credits

The second number is the ceiling on UTR matching and therefore the size of the job left to the amount-based tiers.

## Resolution by tier

| Tier | Rows |
|---|---|
| `tier0_dup_original` | 11 |
| `tier0_dup_reversal` | 11 |
| `tier0_out_of_scope_debit` | 10 |
| `tier1_utr_exact` | 154 |
| `tier2_batch_sum_window` | 39 |
| `tier2b_batch_combination` | 18 |
| `tier3_subset_sum` | 16 |
| `tier4_tolerance` | 3 |
| `tier5_subset_with_tolerance` | 1 |

## Exceptions by reason

| Reason | Rows |
|---|---|
| `ambiguous_multiple_subsets` | 18 |
| `no_gateway_counterpart` | 7 |
| `utr_matched_amount_mismatch` | 3 |

## Per case type

Where the system is strong and where it is not.

| Case type | Rows | Asserted | Precision | Matchable | Recall |
|---|---|---|---|---|---|
| `amount_collision` | 18 | 0 | — | 18 | 0.00% |
| `chargeback_in_batch` | 8 | 8 | 100.00% | 8 | 100.00% |
| `clean_batch` | 99 | 99 | 100.00% | 99 | 100.00% |
| `combined_payout` | 21 | 18 | 100.00% | 21 | 85.71% |
| `dup_original` | 11 | 0 | — | 0 | — |
| `dup_repost` | 11 | 11 | 100.00% | 11 | 100.00% |
| `dup_reversal` | 11 | 0 | — | 0 | — |
| `duplicate_posting` | 33 | 11 | 100.00% | 11 | 100.00% |
| `missing_utr` | 64 | 38 | 100.00% | 56 | 67.86% |
| `out_of_scope_debit` | 10 | 0 | — | 0 | — |
| `refund_in_batch` | 17 | 14 | 100.00% | 15 | 93.33% |
| `rounding_drift` | 5 | 4 | 100.00% | 5 | 80.00% |
| `settlement_hold` | 19 | 17 | 100.00% | 19 | 89.47% |
| `timing_gap` | 40 | 37 | 100.00% | 38 | 97.37% |
| `truncated_narration` | 17 | 17 | 100.00% | 17 | 100.00% |
| `unresolvable` | 7 | 0 | — | 0 | — |
