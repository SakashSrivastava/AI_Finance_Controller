"""The escalation path, driven by a fake backend so no network or key is involved.

The point of these tests is the seam between "the model said something" and "the system
asserted something". They are separate events and only the gate connects them.
"""

from pathlib import Path

import pytest

from recon.agent.client import CachedLLM, CacheMiss, ModelCallFailed, RateLimiter, SpendCapExceeded
from recon.matcher.normalise import load_sources
from recon.pipeline import run_pipeline

DATA = Path("data/42")


class FakeBackend:
    """Returns whatever it is told to, so we can script a liar."""

    def __init__(self, payload: dict | Exception):
        self.payload = payload
        self.calls = 0

    def complete(self, system, user, schema, model):
        self.calls += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload, {"prompt_tokens": 100, "completion_tokens": 20}


def fake_llm(payload, tmp_path, **kwargs):
    return CachedLLM(
        backend=FakeBackend(payload),
        cache_path=tmp_path / "cache.json",
        audit_dir=tmp_path / "audit",
        limiter=RateLimiter(enabled=False),
        **kwargs,
    )


NO_MATCH = {"verdict": "no_match", "payment_ids": [], "invoice_ids": [], "reasoning": "nothing fits", "confidence": 0.1}
CONFIDENT_LIE = {
    "verdict": "match",
    "payment_ids": ["pay_999999"],
    "invoice_ids": ["INV-2026-99999"],
    "reasoning": "This is definitely the one.",
    "confidence": 0.99,
}


def test_cache_prevents_a_second_call(tmp_path):
    llm = fake_llm(NO_MATCH, tmp_path)
    for _ in range(3):
        llm.propose("sys", "user", {"name": "x"}, "model-a")
    assert llm.backend.calls == 1
    assert llm.stats["cache_hits"] == 2


def test_cache_key_separates_models(tmp_path):
    llm = fake_llm(NO_MATCH, tmp_path)
    llm.propose("sys", "user", {"name": "x"}, "model-a")
    llm.propose("sys", "user", {"name": "x"}, "model-b")
    assert llm.backend.calls == 2


def test_offline_mode_never_calls_out(tmp_path):
    llm = CachedLLM(backend=None, cache_path=tmp_path / "c.json", offline=True, audit_dir=None)
    with pytest.raises(CacheMiss):
        llm.propose("sys", "user", {"name": "x"}, "model-a")


def test_committed_cache_replays_without_a_backend(tmp_path):
    warm = fake_llm(NO_MATCH, tmp_path)
    warm.propose("sys", "user", {"name": "x"}, "model-a")
    warm.save()

    replay = CachedLLM(backend=None, cache_path=tmp_path / "cache.json", offline=True, audit_dir=None)
    assert replay.propose("sys", "user", {"name": "x"}, "model-a") == NO_MATCH


def test_call_cap_is_enforced(tmp_path):
    llm = fake_llm(NO_MATCH, tmp_path, max_calls=2)
    llm.propose("s", "a", {"name": "x"}, "m")
    llm.propose("s", "b", {"name": "x"}, "m")
    with pytest.raises(SpendCapExceeded):
        llm.propose("s", "c", {"name": "x"}, "m")


def test_provider_failure_becomes_a_typed_error_not_a_crash(tmp_path):
    llm = fake_llm(RuntimeError("json_validate_failed"), tmp_path)
    with pytest.raises(ModelCallFailed):
        llm.propose("s", "u", {"name": "x"}, "m")


def test_a_lying_model_moves_no_money(tmp_path):
    """The end-to-end claim: a confident, schema-valid, entirely fabricated verdict on
    every single escalated item must not change a single asserted match."""
    baseline = run_pipeline(DATA, use_llm=False)
    lied_to = run_pipeline(DATA, use_llm=True, llm=fake_llm(CONFIDENT_LIE, tmp_path))

    assert lied_to.outcomes, "nothing was escalated, so this proves nothing"
    assert all(o.verdict == "match" for o in lied_to.outcomes)
    assert not any(o.accepted for o in lied_to.outcomes), "the gate let a fabrication through"

    before = {m.bank_txn_id: sorted(m.payment_ids) for m in baseline.bank.matches}
    after = {m.bank_txn_id: sorted(m.payment_ids) for m in lied_to.bank.matches}
    assert before == after
    assert len(baseline.invoice_matches) == len(lied_to.invoice_matches)


def test_rejected_proposals_are_recorded_with_their_evidence(tmp_path):
    result = run_pipeline(DATA, use_llm=True, llm=fake_llm(CONFIDENT_LIE, tmp_path))
    flagged = [e for e in result.bank.exceptions if e.reason_code == "llm_proposal_failed_verification"]
    assert flagged, "a refused proposal should change the exception's reason code"
    evidence = flagged[0].evidence
    assert evidence["model_said"] == ["pay_999999"]
    assert evidence["model_confidence"] == 0.99
    assert evidence["gate_failure"] == "cited_id_does_not_exist"


def test_declining_is_not_treated_as_a_failure(tmp_path):
    result = run_pipeline(DATA, use_llm=True, llm=fake_llm(NO_MATCH, tmp_path))
    assert all(not o.accepted for o in result.outcomes)
    assert all(o.failure is None for o in result.outcomes)
    assert not [e for e in result.bank.exceptions if e.reason_code == "llm_proposal_failed_verification"]


def test_no_llm_run_makes_no_outcomes():
    result = run_pipeline(DATA, use_llm=False)
    assert result.outcomes == []
    assert result.llm_stats == {}
