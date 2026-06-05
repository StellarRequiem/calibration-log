"""The governor must judge honestly: pass an intact, non-suspect, current track;
flag a broken chain (hard), a too-good hit-rate, an implausible Brier, and
overdue resolutions. The >65% auto-suspect line is the operator protocol's, made
mechanical — a too-good record can never quietly pass as a brag.
"""
from datetime import datetime, timezone

from calibration_log.govern import govern, hit_rate, overdue


def _now():
    return datetime(2026, 6, 4, tzinfo=timezone.utc)


# --- hit_rate -------------------------------------------------------------
def test_hit_rate_counts_stated_side():
    # prob>=0.5 states YES, prob<0.5 states NO; a hit is when the stated side won.
    assert hit_rate([(0.9, 1), (0.2, 0)]) == 1.0
    assert hit_rate([(0.9, 0), (0.2, 1)]) == 0.0
    assert hit_rate([(0.9, 1), (0.9, 0)]) == 0.5


def test_hit_rate_empty_is_none():
    assert hit_rate([]) is None


# --- overdue --------------------------------------------------------------
def test_overdue_flags_past_unresolved():
    preds = {"p1": {"by": "2026-01-01T00:00:00Z"},  # past
             "p2": {"by": "2099-01-01T00:00:00Z"}}  # future
    assert overdue(preds, {}, _now()) == ["p1"]


def test_overdue_ignores_resolved_and_unparseable():
    preds = {"p1": {"by": "2026-01-01T00:00:00Z"},  # past but resolved
             "p2": {"by": "not-a-date"}}            # unparseable -> skip
    assert overdue(preds, {"p1": 1}, _now()) == []


# --- govern ---------------------------------------------------------------
def test_clean_track_passes_with_no_findings():
    score = {"chain_ok": True, "chain_msg": "intact", "brier": 0.2}
    resolved = [(0.6, 1), (0.4, 0), (0.7, 1), (0.6, 0), (0.4, 1), (0.3, 1)]  # 50%, n=6
    preds = {f"p{i}": {"by": "2099-01-01T00:00:00Z"} for i in range(6)}
    findings, ok = govern(score, resolved, preds, {}, _now())
    assert ok is True
    assert findings == []


def test_broken_chain_hard_fails_even_without_strict():
    score = {"chain_ok": False, "chain_msg": "hash mismatch at seq 3 — tampered"}
    findings, ok = govern(score, [], {}, {}, _now())
    assert ok is False
    assert any(f["code"] == "chain_broken" and f["level"] == "FAIL" for f in findings)


def test_auto_suspect_hit_rate_flagged_but_warning_by_default():
    score = {"chain_ok": True, "brier": 0.1}
    resolved = [(0.9, 1)] * 6  # 100% hit-rate, n=6 >= MIN
    findings, ok = govern(score, resolved, {}, {}, _now())
    assert any(f["code"] == "hit_rate_auto_suspect" for f in findings)
    assert ok is True  # surfaced, but the chain is what's guaranteed — warning only
    _, ok_strict = govern(score, resolved, {}, {}, _now(), strict=True)
    assert ok_strict is False  # --strict sinks the gate on a suspect record


def test_small_sample_is_not_called_suspect():
    score = {"chain_ok": True, "brier": 0.01}
    resolved = [(0.9, 1)] * 3  # 100% and tiny Brier, but n=3 < MIN_N_FOR_SUSPECT
    findings, _ = govern(score, resolved, {}, {}, _now())
    assert not any(f["level"] == "SUSPECT" for f in findings)


def test_implausibly_low_brier_flagged():
    score = {"chain_ok": True, "brier": 0.01}
    resolved = [(0.5, 1), (0.5, 0), (0.5, 1), (0.5, 0), (0.5, 1)]  # n=5, hit-rate 60%
    findings, _ = govern(score, resolved, {}, {}, _now())
    assert any(f["code"] == "brier_too_low" for f in findings)


def test_overdue_is_stale_warning_then_strict_fail():
    score = {"chain_ok": True, "brier": 0.2}
    preds = {"p1": {"by": "2026-01-01T00:00:00Z"}}  # past, unresolved
    findings, ok = govern(score, [], preds, {}, _now())
    assert any(f["code"] == "overdue_resolutions" and f["level"] == "STALE" for f in findings)
    assert ok is True
    _, ok_strict = govern(score, [], preds, {}, _now(), strict=True)
    assert ok_strict is False
