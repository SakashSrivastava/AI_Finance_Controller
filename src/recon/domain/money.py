"""Money is always an integer number of paise. Rupees exist only for display."""

from __future__ import annotations

Paise = int


def format_paise(amount_paise: int) -> str:
    sign = "-" if amount_paise < 0 else ""
    rupees, paise = divmod(abs(amount_paise), 100)
    return f"{sign}₹{_group_indian(rupees)}.{paise:02d}"


def _group_indian(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])
