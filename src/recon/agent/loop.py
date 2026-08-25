"""The agent loop.

The model is given read-only tools and drives its own investigation: query the batch,
widen the date window, test a combination, test another, then submit. It decides which
tool to call, in what order, and when it has seen enough. Nothing here scripts that
sequence.

What it is *not* allowed to do is decide. `submit` is a proposal, and the proposal still
goes through the verification gate afterwards. The autonomy is spent on investigation and
withheld from the assertion — which is the whole argument, and the reason the loop is safe
to let run unattended over a batch.

`max_steps` is a hard stop. An agent that cannot finish is not given more rope; it is
recorded as unresolved and handed to a human.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from recon.agent.tools import BankToolbox, Investigation, InvoiceToolbox, ToolCall, tool_schemas

MAX_STEPS = 5

BANK_SYSTEM = """You are reconciling one unmatched bank credit against payment gateway settlements.

How the money works:
- The gateway batches payments settling the same day and pays out ONE net amount, so a
  bank credit is the SUM of several settlements, never a single payment.
- Each payment nets gross minus a 2% fee minus 18% GST on that fee.
- Refunds and chargebacks carry negative net and reduce the payout.
- The bank value date can lag settlement by up to 3 days.
- Some payments are withheld from a payout (rolling reserve, risk review), so a credit can
  correspond to a SUBSET of a batch.
- The gateway sometimes pays several whole batches out as one credit.
- Some credits are customers paying directly, bypassing the gateway entirely. Those have NO
  settlement counterpart and the correct answer is no_match.

Deterministic code has already tried exact UTR matching, whole-batch sums, combinations of
whole batches, and bounded subset search, and failed.

Investigate with the tools before answering. Always test_combination before you submit a
match - do not submit a combination you have not verified. If two different combinations
both close, that is genuine ambiguity: submit no_match rather than guessing, because a
wrong match on money is far worse than no match."""

INVOICE_SYSTEM = """You are resolving one mangled invoice reference on a merchant's payment.

The reference is transcribed by the customer, so it arrives corrupted: transposed digits, a
bare number with no prefix, INVOICE instead of INV, truncation, I/1 O/0 S/5 confusion, or
free text wrapped around it.

Rules:
- A payment may settle one invoice, part of one invoice, or several invoices at once.
- Every invoice you cite must belong to the paying customer.
- A payment can never exceed the total of the invoices it settles.
- A reference that is a VALID invoice belonging to a different customer is a corrupted
  reference, not a correct one.

Deterministic matching already tried exact, case-folded, embedded-token and fuzzy lookups.

Investigate with the tools before answering. Use test_invoice_set to check your hypothesis.
Submit no_match if the reference cannot be tied to a specific invoice."""


@dataclass
class AgentResult:
    verdict: str = "needs_human"
    ids: list[str] = field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0
    steps: int = 0
    stopped: str = "no_submit"
    investigation: Investigation = field(default_factory=Investigation)

    @property
    def self_tested(self) -> bool | None:
        """Did the agent's own test say this combination closes? None if never tested."""
        return self.investigation.verdict_was_tested(self.ids)


def run_agent(llm, level: str, system: str, opening: str, toolbox, model: str) -> AgentResult:
    tools = tool_schemas(level)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": opening},
    ]
    result = AgentResult()
    id_field = "payment_ids" if level == "bank" else "invoice_ids"

    for step in range(MAX_STEPS):
        reply = llm.chat(messages, tools, model)
        result.steps = step + 1
        calls = reply.get("tool_calls") or []

        if not calls:
            # The model answered in prose instead of submitting. Prompt once, then stop.
            if result.stopped == "no_submit" and step < MAX_STEPS - 1:
                messages.append({"role": "assistant", "content": reply.get("content") or ""})
                messages.append(
                    {
                        "role": "user",
                        "content": "Call the submit tool with your final answer.",
                    }
                )
                continue
            result.stopped = "no_tool_call"
            break

        messages.append(
            {
                "role": "assistant",
                "content": reply.get("content") or "",
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"]},
                    }
                    for c in calls
                ],
            }
        )

        submitted = False
        for call in calls:
            try:
                args = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}

            if call["name"] == "submit":
                result.verdict = args.get("verdict", "needs_human")
                result.ids = list(args.get(id_field, []) or [])
                result.reasoning = args.get("reasoning", "")
                result.confidence = float(args.get("confidence", 0.0) or 0.0)
                result.stopped = "submitted"
                submitted = True
                break

            output = toolbox.run(call["name"], args)
            result.investigation.record(ToolCall(call["name"], args, output))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(output)[:1200],
                }
            )

        if submitted:
            break
    else:
        result.stopped = "max_steps"

    return result


def bank_opening(exception, narration: str, candidates: list, window_days: int) -> str:
    lines = [
        "UNMATCHED BANK CREDIT",
        f"  id          {exception.bank_txn_id}",
        f"  value_date  {exception.value_date}",
        f"  amount      {exception.amount_paise} paise",
        f"  narration   {narration!r}",
        "",
        f"DETERMINISTIC TIERS FAILED: {exception.reason_code}",
        "",
        f"Nearest unattributed settlements (window {window_days}d, use find_settlements for more):",
    ]
    if not candidates:
        lines.append("  (none in the default window - try find_settlements with a wider one)")
    for s in candidates:
        lines.append(
            f"  {s.payment_id}  utr={s.row.utr}  settled={s.row.settled_at}  net={s.net_paise}"
        )
    lines += ["", "Investigate, then submit."]
    return "\n".join(lines)


def invoice_opening(residue) -> str:
    return "\n".join(
        [
            "PAYMENT WITH AN UNRESOLVED INVOICE REFERENCE",
            f"  payment_id  {residue.payment_id}",
            f"  customer    {residue.customer_name}",
            f"  gross       {residue.gross_amount_paise} paise",
            f"  reference   {residue.raw_ref!r}   <- as received, corrupted",
            "",
            "Investigate, then submit.",
        ]
    )
