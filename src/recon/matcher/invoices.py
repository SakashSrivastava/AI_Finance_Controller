"""Payment to invoice matching.

The second reconciliation level, and a different problem from bank-to-batch. Here the
join key is a reference string a human typed, so the failure mode is transcription, not
arithmetic. Invoices are not consumed exclusively: one invoice can legitimately be
settled by several payments (CONVENTIONS.md section 10).

Tiers run strongest first and stop at the first confident answer. Anything left is
semantic residue, which is the natural place for a language model.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from recon.domain.models import Invoice, Settlement

# CONVENTIONS.md section 10: the observed character confusions.
_FOLD = str.maketrans({"O": "0", "I": "1", "S": "5"})

# The shape of an invoice id, for pulling one out of surrounding free text.
INVOICE_ID_RE = re.compile(r"INV[-\s]?\d{4}[-\s]?\d{4,6}")


def canonical(ref: str) -> str:
    """Fold a reference to a comparable form: case, separators, and confusable glyphs."""
    return re.sub(r"[^A-Za-z0-9]", "", ref.upper()).translate(_FOLD)


def split_refs(raw: str) -> list[str]:
    """One payment may cite several invoices. Trailing annotations are not references."""
    head = raw.split("/")[0]
    return [token.strip() for token in head.split(",") if token.strip()]


@dataclass
class InvoiceMatch:
    payment_id: str
    invoice_ids: list[str]
    tier: str
    confidence: float
    evidence: dict = field(default_factory=dict)


@dataclass
class InvoiceResidue:
    payment_id: str
    raw_ref: str
    customer_name: str
    gross_amount_paise: int
    reason: str
    candidates: list[str] = field(default_factory=list)


class InvoiceMatcher:
    def __init__(self, invoices: list[Invoice], settlements: list[Settlement], fuzzy_threshold: int = 90):
        self.invoices = invoices
        self.settlements = settlements
        self.fuzzy_threshold = fuzzy_threshold

        self.by_id = {i.invoice_id: i for i in invoices}
        self.by_canonical: dict[str, list[Invoice]] = defaultdict(list)
        for inv in invoices:
            self.by_canonical[canonical(inv.invoice_id)].append(inv)

        self.by_customer: dict[str, list[Invoice]] = defaultdict(list)
        for inv in invoices:
            self.by_customer[inv.customer_name].append(inv)

        self._canonical_keys = sorted(self.by_canonical)
        self.stats: dict[str, int] = defaultdict(int)

    def run(self) -> tuple[list[InvoiceMatch], list[InvoiceResidue]]:
        matches: list[InvoiceMatch] = []
        residue: list[InvoiceResidue] = []
        for row in self.settlements:
            match = self._match_one(row)
            if match:
                matches.append(match)
                self.stats[match.tier] += 1
            else:
                residue.append(self._as_residue(row))
                self.stats["residue"] += 1
        return matches, residue

    # ------------------------------------------------------------------ tiers

    def _match_one(self, row: Settlement) -> InvoiceMatch | None:
        tokens = split_refs(row.invoice_ref)
        if not tokens:
            return None

        exact = [self.by_id[t] for t in tokens if t in self.by_id]
        if len(exact) == len(tokens) and all(
            i.customer_name == row.customer_name for i in exact
        ):
            return InvoiceMatch(
                row.payment_id,
                [i.invoice_id for i in exact],
                "inv1_exact_ref",
                1.0,
                {"matched_on": "reference cited verbatim, customer corroborates"},
            )
        if len(exact) == len(tokens):
            self.stats["exact_ref_wrong_customer"] += 1

        folded = self._resolve_all(tokens, row, self._canonical_lookup)
        if folded:
            return InvoiceMatch(
                row.payment_id,
                folded,
                "inv2_canonical_ref",
                0.95,
                {"matched_on": "reference matched after folding case, separators and O/0 I/1 S/5"},
            )

        embedded = self._resolve_all(tokens, row, self._embedded_lookup)
        if embedded:
            return InvoiceMatch(
                row.payment_id,
                embedded,
                "inv3_embedded_id",
                0.9,
                {"matched_on": "invoice-shaped token extracted from surrounding free text"},
            )

        fuzzy = self._resolve_all(tokens, row, self._fuzzy_lookup)
        if fuzzy:
            return InvoiceMatch(
                row.payment_id,
                fuzzy,
                "inv4_fuzzy_ref",
                0.75,
                {"matched_on": f"fuzzy reference match at or above {self.fuzzy_threshold}"},
            )

        amount = self._amount_lookup(row)
        if amount:
            return InvoiceMatch(
                row.payment_id,
                amount,
                "inv5_amount_and_customer",
                0.7,
                {"matched_on": "reference unusable; unique invoice by exact amount and customer"},
            )
        return None

    def _resolve_all(self, tokens: list[str], row: Settlement, lookup) -> list[str] | None:
        """Every cited reference must resolve, or the payment is not matched at all.

        A reference that is a *valid* invoice id belonging to a different customer is a
        corrupted reference, not a correct one. Transposing two digits routinely produces
        exactly that, and string matching cannot tell the difference - only the customer
        can. This is the invoice-level form of the rule that decides the whole project:
        a plausible-looking key still has to be corroborated before money moves.
        """
        out = []
        for token in tokens:
            hit = self.by_id.get(token)
            if hit is not None and hit.customer_name != row.customer_name:
                hit = None
            if hit is None:
                hit = lookup(token, row)
            if hit is None:
                return None
            out.append(hit.invoice_id if isinstance(hit, Invoice) else hit)
        return out

    def _canonical_lookup(self, token: str, row: Settlement) -> Invoice | None:
        hits = [
            i
            for i in self.by_canonical.get(canonical(token), [])
            if i.customer_name == row.customer_name
        ]
        return hits[0] if len(hits) == 1 else None

    def _embedded_lookup(self, token: str, row: Settlement) -> Invoice | None:
        """CONVENTIONS.md 10: references arrive wrapped in stray words and punctuation.

        Pulling an invoice-shaped token out of free text is pattern work, so it belongs
        in code. What is left after this - transposed digits, bare numbers with no
        prefix - cannot be resolved by pattern at all and is genuine semantic residue.
        """
        found = INVOICE_ID_RE.search(token.upper())
        if not found:
            return None
        hits = [
            i
            for i in self.by_canonical.get(canonical(found.group(0)), [])
            if i.customer_name == row.customer_name
        ]
        return hits[0] if len(hits) == 1 else None

    def _fuzzy_lookup(self, token: str, row: Settlement) -> Invoice | None:
        """Fuzzy matching is only allowed to break a tie the customer already narrowed."""
        pool = self.by_customer.get(row.customer_name, [])
        if not pool:
            return None
        keys = [canonical(i.invoice_id) for i in pool]
        hits = process.extract(
            canonical(token), keys, scorer=fuzz.ratio, score_cutoff=self.fuzzy_threshold, limit=2
        )
        if len(hits) != 1:
            return None
        return pool[hits[0][2]]

    def _amount_lookup(self, row: Settlement) -> list[str] | None:
        pool = [
            i
            for i in self.by_customer.get(row.customer_name, [])
            if i.gross_amount_paise == row.gross_amount_paise
        ]
        return [pool[0].invoice_id] if len(pool) == 1 else None

    def _as_residue(self, row: Settlement) -> InvoiceResidue:
        pool = self.by_customer.get(row.customer_name, [])
        keys = [canonical(i.invoice_id) for i in pool]
        near = process.extract(
            canonical(split_refs(row.invoice_ref)[0] if split_refs(row.invoice_ref) else ""),
            keys,
            scorer=fuzz.ratio,
            limit=8,
        )
        return InvoiceResidue(
            payment_id=row.payment_id,
            raw_ref=row.invoice_ref,
            customer_name=row.customer_name,
            gross_amount_paise=row.gross_amount_paise,
            reason="reference did not resolve deterministically",
            candidates=[pool[h[2]].invoice_id for h in near],
        )
