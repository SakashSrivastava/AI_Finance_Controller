"""Bounded subset-sum search with ambiguity detection.

Two design choices worth defending:

**No dynamic programming over paise.** A four-lakh-rupee credit is 40,000,000 paise, so a
DP table indexed by amount is not allocatable. Sorted-descending depth-first search with
suffix-sum pruning is milliseconds at the sizes that actually occur (10-30 candidates in
a three-day window).

**A deterministic node budget, not a wall-clock timeout.** A timeout would make the same
seed produce different headline numbers on a loaded machine. The budget is a pure function
of the input, so results are reproducible.

The search **counts solutions and stops at two**. You cannot declare a match ambiguous
without proving a second solution exists, and finding one is a different algorithm from
finding any.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_SOLUTIONS = 2


@dataclass
class SubsetSearchResult:
    solutions: list[list[int]]
    nodes: int
    budget_exceeded: bool

    @property
    def is_unique(self) -> bool:
        return len(self.solutions) == 1 and not self.budget_exceeded

    @property
    def is_ambiguous(self) -> bool:
        return len(self.solutions) >= MAX_SOLUTIONS


def find_subsets(
    amounts: list[int],
    target: int,
    max_size: int = 12,
    node_budget: int = 200_000,
    tolerance: int = 0,
) -> SubsetSearchResult:
    """Find up to two distinct subsets of `amounts` summing to `target` within tolerance.

    `amounts` must be non-negative. Refunds and chargebacks are not freely selectable
    candidates (CONVENTIONS.md section 7) - the caller folds them into the target instead.
    """
    if any(a < 0 for a in amounts):
        raise ValueError("subset search requires non-negative amounts")

    order = sorted(range(len(amounts)), key=lambda i: -amounts[i])
    values = [amounts[i] for i in order]
    n = len(values)

    suffix = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix[i] = suffix[i + 1] + values[i]

    solutions: list[list[int]] = []
    state = {"nodes": 0, "exceeded": False}

    def dfs(i: int, remaining: int, chosen: list[int]) -> None:
        if state["exceeded"] or len(solutions) >= MAX_SOLUTIONS:
            return
        state["nodes"] += 1
        if state["nodes"] > node_budget:
            state["exceeded"] = True
            return
        if abs(remaining) <= tolerance:
            solutions.append(sorted(order[j] for j in chosen))
            return
        if i >= n or len(chosen) >= max_size:
            return
        if remaining < -tolerance:
            return
        if remaining - tolerance > suffix[i]:
            return

        chosen.append(i)
        dfs(i + 1, remaining - values[i], chosen)
        chosen.pop()
        dfs(i + 1, remaining, chosen)

    dfs(0, target, [])
    return SubsetSearchResult(
        solutions=solutions, nodes=state["nodes"], budget_exceeded=state["exceeded"]
    )
