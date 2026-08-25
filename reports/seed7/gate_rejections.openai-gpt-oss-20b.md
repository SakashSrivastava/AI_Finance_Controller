# Proposals the verification gate refused

Model `openai/gpt-oss-20b`, held-out seed. 7 of 20 proposals refused.

Reproduce with `recon compare --data data/7` - it replays the committed cache, so no API key is needed.

## `bank_000005` - another_subset_also_reconciles

**The model proposed** `['pay_001343']` at confidence 0.95.

> The bank credit of 58,929,664 paise matches exactly the net amount of settlement pay_001343. No other combination of the listed settlements sums to this amount, so the credit is attributable to that single settlement.

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
  "credit_paise": 58929664,
  "delta_paise": 0,
  "proposed_total_paise": 58929664,
  "subsets_that_reconcile": 2,
  "tolerance_paise": 5
}
```

## `bank_000087` - amounts_do_not_sum_to_the_credit

**The model proposed** `['pay_000896', 'pay_000897', 'pay_000898', 'pay_000899', 'pay_000900', 'pay_000901', 'pay_000902', 'pay_000903', 'pay_000904', 'pay_000905']` at confidence 0.9.

> The bank credit of 81,615,154 paise matches exactly the net of settlement pay_000905 alone, but also matches the sum of all other settlements except pay_000126. In typical gateway payouts, only a few payments are withheld (e.g., due to rolling reserve or risk review). Withholding all but one payment (pay_000905) is highly unlikely, whereas withholding a single larger payment (pay_000126) is plausible. Therefore the most reasonable subset that explains the credit is all settlements except pay_000126, which sum to 81,615,154 paise.

**The gate checked:**

| Check | Result |
|---|---|
| `non_empty` | pass |
| `ids_exist` | pass |
| `not_already_attributed` | pass |
| `inside_date_window` | pass |
| `sums_to_credit` | **FAIL** |

**Arithmetic:**

```json
{
  "credit_paise": 81615154,
  "delta_paise": -81615154,
  "proposed_total_paise": 163230308,
  "tolerance_paise": 5
}
```

## `bank_000134` - another_subset_also_reconciles

**The model proposed** `['pay_001007']` at confidence 0.92.

> The bank credit of 30,197,126 paise matches exactly the net of settlement pay_001007. Although another subset of three settlements also sums to the same amount, the presence of a single settlement matching the credit and the possibility that the other three were withheld (rolling reserve/risk review) makes pay_001007 the most plausible match.

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

## `bank_000185` - another_subset_also_reconciles

**The model proposed** `['pay_001056']` at confidence 0.9.

> The bank credit amount of 71,920,405 paise matches exactly the net of settlement pay_001056. Although another subset of settlements also sums to the same amount, the single settlement provides a clear, unambiguous match to the NEFT credit from Razorpay.

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

## `bank_000202` - another_subset_also_reconciles

**The model proposed** `['pay_000043', 'pay_000044', 'pay_000045', 'pay_000046', 'pay_000047', 'pay_000048', 'pay_000049']` at confidence 0.95.

> The bank credit of 78,377,195 paise must be the sum of multiple settlements, not a single one, as per gateway rules. The single settlement pay_000050 equals the credit amount, but that violates the rule that a credit is never a single payment. The only other subset that sums to the same amount is the combination of all remaining settlements (pay_000046 through pay_000048). Their net amounts add up exactly to 78,377,195 paise, satisfying the requirement. Therefore the correct match is the subset of all other settlements.

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

## `bank_000269` - another_subset_also_reconciles

**The model proposed** `['pay_000092']` at confidence 0.95.

> The bank credit amount (Rs 1,530,806.40) matches exactly the net of settlement pay_000092 (153,080,640 paise). The narration ‘BY TRANSFER‑RAZORPAY SOFTW’ indicates a transfer from Razorpay, and the UTR HDFCN00000000024 in the settlement list corresponds to that transfer. Although a subset of other settlements could mathematically sum to the same amount, the direct match of amount, UTR, and narration strongly points to pay_000092 as the correct settlement.

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
  "credit_paise": 153080640,
  "delta_paise": 0,
  "proposed_total_paise": 153080640,
  "subsets_that_reconcile": 2,
  "tolerance_paise": 5
}
```

## `bank_000270` - amounts_do_not_sum_to_the_credit

**The model proposed** `['pay_000084', 'pay_000085', 'pay_000086', 'pay_000087', 'pay_000088', 'pay_000089', 'pay_000090', 'pay_000091', 'pay_000092']` at confidence 0.9.

> The bank credit of Rs 1,530,806.40 (153,080,640 paise) matches the net sum of all settlements except pay_000783. The sum of the nine listed payments equals exactly the credit amount, whereas the single payment pay_000092 also equals the amount but would imply a batch containing only that payment, which is inconsistent with the batch’s other settlements. Thus the credit corresponds to the batch comprising all payments settled on 2026‑06‑26 (excluding the 24‑June settlement).

**The gate checked:**

| Check | Result |
|---|---|
| `non_empty` | pass |
| `ids_exist` | pass |
| `not_already_attributed` | pass |
| `inside_date_window` | pass |
| `sums_to_credit` | **FAIL** |

**Arithmetic:**

```json
{
  "credit_paise": 153080640,
  "delta_paise": -153080640,
  "proposed_total_paise": 306161280,
  "tolerance_paise": 5
}
```

