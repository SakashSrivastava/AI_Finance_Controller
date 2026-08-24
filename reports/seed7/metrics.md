# Reconciliation results

## Headline

| Metric | Value |
|---|---|
| **Precision (strict set equality)** | **100.00%** |
| Recall (strict) | 94.42% |
| Mean Jaccard overlap | 1.000 |
| False matches | 0 of 237 asserted |
| False matches on unresolvable rows | 0 |
| Coverage | 91.00% |
| Bank rows | 289 |
| Exceptions | 26 |
| Value under investigation | ₹1,01,23,063.01 |

Agreement is **strict set equality**: a match is a set of payment ids, and getting four of five right is a wrong answer because the money does not reconcile. Mean Jaccard is reported alongside so near misses can be told apart from wild guesses.

## UTR extraction

- Parser recall (UTR present in narration): **100.00%** (193/193)
- UTR available at all (after missing and capped narrations): **76.89%** of 251 settlement credits

The second number is the ceiling on UTR matching and therefore the size of the job left to the amount-based tiers.

## Resolution by tier

| Tier | Rows |
|---|---|
| `tier0_dup_original` | 8 |
| `tier0_dup_reversal` | 8 |
| `tier0_out_of_scope_debit` | 10 |
| `tier1_utr_exact` | 148 |
| `tier2_batch_sum_window` | 43 |
| `tier2b_batch_combination` | 12 |
| `tier3_subset_sum` | 22 |
| `tier4_tolerance` | 11 |
| `tier5_subset_with_tolerance` | 1 |

## Exceptions by reason

| Reason | Rows |
|---|---|
| `ambiguous_multiple_subsets` | 10 |
| `no_gateway_counterpart` | 13 |
| `utr_matched_amount_mismatch` | 3 |

## Per case type

Where the system is strong and where it is not.

| Case type | Rows | Asserted | Precision | Matchable | Recall |
|---|---|---|---|---|---|
| `amount_collision` | 26 | 16 | 100.00% | 26 | 61.54% |
| `chargeback_in_batch` | 11 | 11 | 100.00% | 11 | 100.00% |
| `clean_batch` | 94 | 94 | 100.00% | 94 | 100.00% |
| `combined_payout` | 21 | 13 | 100.00% | 19 | 68.42% |
| `dup_original` | 8 | 0 | 0.00% | 0 | 0.00% |
| `dup_repost` | 8 | 8 | 100.00% | 8 | 100.00% |
| `dup_reversal` | 8 | 0 | 0.00% | 0 | 0.00% |
| `duplicate_posting` | 24 | 8 | 100.00% | 8 | 100.00% |
| `missing_utr` | 47 | 35 | 100.00% | 43 | 81.40% |
| `out_of_scope_debit` | 10 | 0 | 0.00% | 0 | 0.00% |
| `refund_in_batch` | 11 | 10 | 100.00% | 11 | 90.91% |
| `rounding_drift` | 14 | 12 | 100.00% | 14 | 85.71% |
| `settlement_hold` | 25 | 23 | 100.00% | 25 | 92.00% |
| `timing_gap` | 40 | 34 | 100.00% | 38 | 89.47% |
| `truncated_narration` | 34 | 30 | 100.00% | 32 | 93.75% |
| `unresolvable` | 12 | 0 | 0.00% | 0 | 0.00% |
