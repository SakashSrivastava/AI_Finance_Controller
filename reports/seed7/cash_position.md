# Cash position

As of **2026-06-30**.

| Where the money is | Count | Value |
|---|---|---|
| Settled and in the bank | 232 | ₹11,01,54,747.87 |
| In flight (settled within the last 3 days, not yet on the statement) | 0 | ₹0.00 |
| Settled but unattributed | 98 | ₹1,40,62,794.24 |
| **Under investigation** | 20 | **₹1,16,84,069.34** |
| Unresolvable from available data | 7 | ₹6,84,420.40 |

`Under investigation` is the rupee value a human still has to clear, counted on the bank side. It is the number a finance team acts on, and it is the reason an exception list matters more than a match rate.

`Settled but unattributed` is the gateway-side view, and it deliberately mixes two things this data cannot separate: payments the gateway withheld against a reserve or a risk review, and payments it did pay out that could not be tied to a specific credit. Distinguishing them needs the gateway's own payout report. It is kept apart from `in flight` because treating either as incoming cash would overstate the position.

## Receivables

| Ageing | Invoices | Value |
|---|---|---|
| Not yet due | 28 | ₹25,72,582.52 |
| Overdue 0-30 days | 64 | ₹68,37,585.01 |
| Overdue 31-60 days | 75 | ₹76,54,546.78 |
| Overdue 61+ days | 28 | ₹30,86,643.06 |
| **Total receivables** | | **₹2,01,51,357.37** |

## Cost of collection

| Item | Value |
|---|---|
| Gateway fees | ₹26,15,607.86 |
| GST on fees | ₹4,70,809.52 |
| **Total** | **₹30,86,417.38** |
