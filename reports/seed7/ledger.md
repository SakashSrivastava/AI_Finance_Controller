# The books

291 journal entries, one per bank transaction, derived entirely from the reconciliation.

## Trial balance

| Account | | Balance |
|---|---|---|
| Accounts receivable | Cr | ₹11,61,77,693.69 |
| Bank | Dr | ₹12,13,23,853.12 |
| Chargebacks | Dr | ₹14,87,895.31 |
| GST input credit | Dr | ₹4,18,959.77 |
| Gateway fees | Dr | ₹23,27,553.95 |
| Other business outflows | Dr | ₹11,99,384.49 |
| Refunds and sales returns | Dr | ₹17,88,536.80 |
| Rounding difference | Cr | ₹0.01 |
| Suspense | Cr | ₹1,23,68,489.74 |

| **Total debits** | | **₹14,30,15,765.92** |
| **Total credits** | | **₹14,30,15,765.92** |

**Balanced: True**

## Why this is a check and not a rendering

Double entry is an arithmetic invariant over the whole reconciliation that never consults the matcher's logic. If a batch were mis-attributed in a way that moved amounts, the trial balance would stop closing.

The tie-out below is the same idea. The exception queue is produced by the matcher; the suspense balance falls out of bookkeeping over every bank row. Two independent routes, one number.

| | Value |
|---|---|
| Suspense balance | ₹1,23,68,489.74 |
| Exception queue | ₹1,23,68,489.74 |
| **Agree** | **True** |

Gateway fees and the GST on them never arrive as a payment - they are netted before the money reaches the bank. Reconstructing them from the fee model is the only way they are ever recorded, and the GST input credit is real money the merchant can claim back.
