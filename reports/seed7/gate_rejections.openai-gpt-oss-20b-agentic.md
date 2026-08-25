# Proposals the verification gate refused

Model `openai/gpt-oss-20b agentic`, held-out seed. 8 of 10 proposals refused.

Reproduce with `recon compare --data data/7` - it replays the committed cache, so no API key is needed.

## `bank_000087` - another_subset_also_reconciles

**The model proposed** `['pay_000905']` at confidence 0.99.

> The bank credit of 81,615,154 paise matches exactly the net amount of settlement pay_000905 (UTR KKBKN00000000180). The batch total equals the credit amount and no other combination of settlements is needed. Therefore this is a clear match.

**The gate checked:**

| Check | Result |
|---|---|
| `non_empty` | pass |
| `ids_exist` | pass |
| `not_already_attributed` | pass |
| `inside_date_window` | pass |
| `sums_to_credit` | pass |
| `uniquely_determined` | **FAIL** |

**Arithmetic:**

```json
{
  "credit_paise": 81615154,
  "delta_paise": 0,
  "proposed_total_paise": 81615154,
  "subsets_that_reconcile": 2,
  "tolerance_paise": 5
}
```

## `bank_000088` - another_subset_also_reconciles

**The model proposed** `['pay_000905']` at confidence 0.99.

> The bank credit amount 81,615,154 paise matches exactly the net amount of settlement pay_000905 (UTR KKBKN00000000180, settled 2026-04-29). No other combination of unattributed settlements sums to this amount within the 3‑day window, and deterministic tiers already failed only due to ambiguity. Since the exact match is found, we can confidently submit this settlement as the match.

**The gate checked:**

| Check | Result |
|---|---|
| `non_empty` | pass |
| `ids_exist` | pass |
| `not_already_attributed` | pass |
| `inside_date_window` | pass |
| `sums_to_credit` | pass |
| `uniquely_determined` | **FAIL** |

**Arithmetic:**

```json
{
  "credit_paise": 81615154,
  "delta_paise": 0,
  "proposed_total_paise": 81615154,
  "subsets_that_reconcile": 2,
  "tolerance_paise": 5
}
```

## `bank_000133` - another_subset_also_reconciles

**The model proposed** `['pay_001007']` at confidence 0.99.

> The bank credit amount 30197126 paise matches exactly the net amount of settlement pay_001007 (UTR UTIBN00000000200) settled on 2026-05-16. The get_batch confirms the batch total equals the credit and the settlement is unattributed. No other combination of settlements sums to this amount within the 3‑day window. Therefore the credit is reconciled to pay_001007.

**The gate checked:**

| Check | Result |
|---|---|
| `non_empty` | pass |
| `ids_exist` | pass |
| `not_already_attributed` | pass |
| `inside_date_window` | pass |
| `sums_to_credit` | pass |
| `uniquely_determined` | **FAIL** |

**Arithmetic:**

```json
{
  "credit_paise": 30197126,
  "delta_paise": 0,
  "proposed_total_paise": 30197126,
  "subsets_that_reconcile": 2,
  "tolerance_paise": 5
}
```

## `bank_000184` - another_subset_also_reconciles

**The model proposed** `['pay_001047', 'pay_001048', 'pay_001049', 'pay_001050', 'pay_001051', 'pay_001052', 'pay_001053', 'pay_001054', 'pay_001055']` at confidence 0.9.

> The bank credit amount 71920405 paise matches exactly the sum of the nine settlements from UTR HDFCN00000000209. Although a single settlement pay_001056 also matches the amount, it is a separate UTR and would not be part of the gateway’s payout batch. The credit is a NEFT credit to Razorpay’s bank account, which corresponds to the net payout of the batch. Therefore the correct match is the nine settlements.

**The gate checked:**

| Check | Result |
|---|---|
| `non_empty` | pass |
| `ids_exist` | pass |
| `not_already_attributed` | pass |
| `inside_date_window` | pass |
| `sums_to_credit` | pass |
| `uniquely_determined` | **FAIL** |

**Arithmetic:**

```json
{
  "credit_paise": 71920405,
  "delta_paise": 0,
  "proposed_total_paise": 71920405,
  "subsets_that_reconcile": 2,
  "tolerance_paise": 5
}
```

## `bank_000185` - another_subset_also_reconciles

**The model proposed** `['pay_001056']` at confidence 1.0.

> The bank credit amount exactly matches the net of settlement pay_001056 (71920405 paise). No other combination of settlements yields the same amount, and the deterministic tier already identified this as a single‑payment match. Therefore we can confidently submit this match.

**The gate checked:**

| Check | Result |
|---|---|
| `non_empty` | pass |
| `ids_exist` | pass |
| `not_already_attributed` | pass |
| `inside_date_window` | pass |
| `sums_to_credit` | pass |
| `uniquely_determined` | **FAIL** |

**Arithmetic:**

```json
{
  "credit_paise": 71920405,
  "delta_paise": 0,
  "proposed_total_paise": 71920405,
  "subsets_that_reconcile": 2,
  "tolerance_paise": 5
}
```

## `bank_000195` - another_subset_also_reconciles

**The model proposed** `['pay_001247']` at confidence 0.99.

> The bank credit amount 4476261 paise matches exactly the net of settlement pay_001247 (UTR HDFCN00000000255) which is unattributed and settled on 2026-06-03. No other combination of settlements sums to this amount within the 3‑day window. Therefore this settlement is the correct match.

**The gate checked:**

| Check | Result |
|---|---|
| `non_empty` | pass |
| `ids_exist` | pass |
| `not_already_attributed` | pass |
| `inside_date_window` | pass |
| `sums_to_credit` | pass |
| `uniquely_determined` | **FAIL** |

**Arithmetic:**

```json
{
  "credit_paise": 4476261,
  "delta_paise": 0,
  "proposed_total_paise": 4476261,
  "subsets_that_reconcile": 2,
  "tolerance_paise": 5
}
```

## `bank_000196` - another_subset_also_reconciles

**The model proposed** `['pay_001247']` at confidence 0.99.

> The bank credit amount 4476261 paise matches exactly the net of settlement pay_001247, which has UTR HDFCN00000000255. The batch for this UTR totals 4476261 paise and contains only this settlement, which is unattributed. test_combination confirms the sum equals the credit. Therefore this settlement is the correct match.

**The gate checked:**

| Check | Result |
|---|---|
| `non_empty` | pass |
| `ids_exist` | pass |
| `not_already_attributed` | pass |
| `inside_date_window` | pass |
| `sums_to_credit` | pass |
| `uniquely_determined` | **FAIL** |

**Arithmetic:**

```json
{
  "credit_paise": 4476261,
  "delta_paise": 0,
  "proposed_total_paise": 4476261,
  "subsets_that_reconcile": 2,
  "tolerance_paise": 5
}
```

## `bank_000201` - another_subset_also_reconciles

**The model proposed** `['pay_000050']` at confidence 0.99.

> The bank credit amount 78377195 paise matches exactly the net amount of settlement pay_000050 (UTR HDFCN00000000014). The batch total equals the credit, and the settlement is unattributed. Therefore this settlement is the correct match.

**The gate checked:**

| Check | Result |
|---|---|
| `non_empty` | pass |
| `ids_exist` | pass |
| `not_already_attributed` | pass |
| `inside_date_window` | pass |
| `sums_to_credit` | pass |
| `uniquely_determined` | **FAIL** |

**Arithmetic:**

```json
{
  "credit_paise": 78377195,
  "delta_paise": 0,
  "proposed_total_paise": 78377195,
  "subsets_that_reconcile": 2,
  "tolerance_paise": 5
}
```

