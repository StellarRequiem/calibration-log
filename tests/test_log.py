"""The log must score honestly and detect tampering."""
import json

import pytest

from calibration_log.log import CalibrationLog


def test_predict_then_pending(tmp_path):
    log = CalibrationLog(tmp_path / "p.jsonl")
    log.predict("rain tomorrow", 0.7, "2026-07-01")
    log.predict("snow in july", 0.1, "2026-07-31")
    s = log.score()
    assert (s["total"], s["resolved"], s["pending"]) == (2, 0, 2)
    assert s["brier"] is None


def test_resolve_and_brier(tmp_path):
    log = CalibrationLog(tmp_path / "p.jsonl")
    log.predict("a", 0.9, "2026-07-01")   # p1
    log.predict("b", 0.2, "2026-07-01")   # p2
    log.resolve("p1", "yes")              # (0.9-1)^2 = 0.01
    log.resolve("p2", "no")               # (0.2-0)^2 = 0.04
    s = log.score()
    assert s["resolved"] == 2
    assert abs(s["brier"] - 0.025) < 1e-9   # mean(0.01, 0.04)
    assert s["chain_ok"]


def test_probability_bounds(tmp_path):
    log = CalibrationLog(tmp_path / "p.jsonl")
    with pytest.raises(ValueError):
        log.predict("x", 1.0, "2026")
    with pytest.raises(ValueError):
        log.predict("x", 0.0, "2026")


def test_resolve_guards(tmp_path):
    log = CalibrationLog(tmp_path / "p.jsonl")
    with pytest.raises(KeyError):
        log.resolve("p1", "yes")            # unknown
    log.predict("a", 0.6, "2026")
    log.resolve("p1", "yes")
    with pytest.raises(ValueError):
        log.resolve("p1", "no")             # double-resolve


def test_tamper_is_detected(tmp_path):
    p = tmp_path / "p.jsonl"
    log = CalibrationLog(p)
    log.predict("a", 0.6, "2026")
    log.predict("b", 0.3, "2026")
    lines = p.read_text().splitlines()
    row = json.loads(lines[0])
    row["event_data"]["prob"] = 0.99        # rewrite a past prediction
    lines[0] = json.dumps(row)
    p.write_text("\n".join(lines) + "\n")
    assert not log.score()["chain_ok"]
