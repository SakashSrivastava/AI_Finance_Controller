"""Matcher tuning. Every threshold here is a deliberate choice, not a magic number."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatcherConfig:
    # CONVENTIONS.md 3: value date may lag settlement by 1-3 days.
    date_window_days: int = 3
    # A duplicate posting resolves within a few days of the original.
    dup_window_days: int = 5
    # CONVENTIONS.md 2: fee rounding can leave a few paise of drift.
    tolerance_paise: int = 5
    max_subset_size: int = 12
    # Deterministic work cap. A wall-clock timeout would make results depend on machine
    # load, so the same seed could produce different headline numbers on a busy laptop.
    node_budget: int = 200_000
    fuzzy_threshold: int = 90


DEFAULT_MATCHER_CONFIG = MatcherConfig()
