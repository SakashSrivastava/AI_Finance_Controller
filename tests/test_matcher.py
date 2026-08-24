from pathlib import Path

import pytest

from recon.eval.metrics import evaluate
from recon.matcher.engine import Reconciler
from recon.matcher.normalise import extract_utr, load_sources

DATA = Path("data/42")


@pytest.fixture(scope="module")
def sources():
    return load_sources(DATA)


@pytest.fixture(scope="module")
def result(sources):
    return Reconciler(sources).run()


def test_matcher_and_agent_never_read_ground_truth():
    """Enforced as a test, not a convention. Only src/recon/eval may touch these files."""
    offenders = []
    for path in Path("src/recon").rglob("*.py"):
        if path.parts[2] in ("matcher", "agent", "controller"):  # generator authors it
            if "ground_truth" in path.read_text(encoding="utf-8"):
                offenders.append(str(path))
    assert not offenders, f"ground truth referenced outside eval: {offenders}"


def test_matching_is_idempotent(sources):
    """Re-running must not double-post. This is the characteristic failure of recon tools."""
    a = Reconciler(sources).run()
    b = Reconciler(sources).run()
    assert [m.model_dump() for m in a.matches] == [m.model_dump() for m in b.matches]
    assert [e.model_dump() for e in a.exceptions] == [e.model_dump() for e in b.exceptions]


def test_no_payment_is_asserted_against_two_bank_rows(result):
    seen: dict[str, str] = {}
    for m in result.matches:
        for payment_id in m.payment_ids:
            assert payment_id not in seen, f"{payment_id} claimed by {seen.get(payment_id)} and {m.bank_txn_id}"
            seen[payment_id] = m.bank_txn_id


def test_every_bank_row_is_either_resolved_or_an_exception(result, sources):
    accounted = {m.bank_txn_id for m in result.matches} | {e.bank_txn_id for e in result.exceptions}
    assert accounted == {b.txn_id for b in sources.bank}


def test_no_exception_uses_a_vague_reason(result):
    assert all(e.reason_code != "unmatched" for e in result.exceptions)
    assert all(e.reason_code for e in result.exceptions)


def test_evaluation_can_actually_fail(result):
    """A harness that cannot report a bad score is not measuring anything.

    Corrupt one asserted match and confirm precision drops and the false-match count rises.
    """
    clean = evaluate(DATA, result)
    assert clean["precision_strict"] == 1.0

    corrupted = result.model_copy() if hasattr(result, "model_copy") else result
    victim = next(m for m in result.matches if m.payment_ids)
    original = list(victim.payment_ids)
    victim.payment_ids = original + ["pay_999999"]
    try:
        dirty = evaluate(DATA, corrupted)
        assert dirty["precision_strict"] < clean["precision_strict"]
        assert dirty["false_matches"] == clean["false_matches"] + 1
        assert dirty["mean_jaccard"] < 1.0
    finally:
        victim.payment_ids = original


@pytest.mark.parametrize(
    "narration, expected",
    [
        ("NEFT-HDFCN00000000123-RAZORPAY SOFTWARE PVT LTD", "HDFCN00000000123"),
        ("IMPS/ICICN00000000045/RAZORPAYSOFT", "ICICN00000000045"),
        ("UPI-RAZORPAY-UTIBN00000000900", "UTIBN00000000900"),
        ("CMS/SBINN00000000001", "SBINN00000000001"),
        ("MB:KKBKN00000000777 RZPY SETTLEMENT", "KKBKN00000000777"),
        ("BY TRANSFER-NEFT*HDFCN00000000321*RAZORPAY", "HDFCN00000000321"),
        ("RAZORPAY SETTLEMENT CREDIT", None),
        ("GATEWAY PAYOUT RAZORPAY", None),
        ("BY TRANSFER FROM RAZORPAY SOFTWARE PVT LTD N", None),
    ],
)
def test_utr_regex_against_every_documented_narration_shape(narration, expected):
    assert extract_utr(narration)[0] == expected


def test_truncated_utr_is_a_hint_not_a_key():
    _, fragment = extract_utr("TRF FROM RAZORPAY REF SBINN000000002")
    assert fragment == "SBINN000000002"
    assert extract_utr("TRF FROM RAZORPAY REF SBINN000000002")[0] is None
