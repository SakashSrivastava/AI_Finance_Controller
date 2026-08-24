import pytest

from recon.matcher.subsetsum import find_subsets


def test_finds_the_known_subset():
    r = find_subsets([500, 300, 200, 900], target=700)
    assert r.is_unique
    assert sorted(r.solutions[0]) == [0, 2]  # 500 + 200


def test_uses_every_element_when_that_is_the_answer():
    r = find_subsets([100, 200, 300], target=600)
    assert r.is_unique
    assert sorted(r.solutions[0]) == [0, 1, 2]


def test_reports_no_solution_rather_than_guessing():
    r = find_subsets([500, 300, 200], target=1_000_000)
    assert r.solutions == []
    assert not r.is_unique


def test_two_distinct_subsets_are_ambiguous_not_a_match():
    # 400+600 and 300+700 both hit 1000. Guessing between them would be inventing money.
    r = find_subsets([400, 600, 300, 700], target=1000)
    assert r.is_ambiguous
    assert not r.is_unique


def test_equal_amounts_are_genuinely_ambiguous():
    # Two payments of the same value: you cannot tell which one settled.
    r = find_subsets([250, 250, 900], target=250)
    assert r.is_ambiguous


def test_tolerance_admits_rounding_drift():
    r = find_subsets([500, 300], target=802, tolerance=5)
    assert r.is_unique
    assert sorted(r.solutions[0]) == [0, 1]


def test_tolerance_still_refuses_when_several_subsets_fit_the_band():
    r = find_subsets([100, 101, 500], target=100, tolerance=5)
    assert r.is_ambiguous


def test_max_size_is_respected():
    r = find_subsets([1] * 20, target=15, max_size=12)
    assert r.solutions == []


def test_budget_exceeded_is_reported_not_silently_wrong():
    # A hard instance with a tiny budget must say so rather than claim no solution.
    amounts = [2**i for i in range(30)]
    r = find_subsets(amounts, target=(2**30) - 1, max_size=30, node_budget=50)
    assert r.budget_exceeded
    assert not r.is_unique


def test_search_is_deterministic():
    amounts = [937, 412, 655, 208, 1301, 77, 549]
    first = find_subsets(amounts, target=1560)
    for _ in range(5):
        assert find_subsets(amounts, target=1560).solutions == first.solutions


def test_negative_amounts_are_rejected():
    with pytest.raises(ValueError):
        find_subsets([100, -50], target=50)
