"""The `verify` CLI is the runnable gate: exit 0 on a clean track, 1 on a broken
chain, 2 when the track is missing. Anyone can re-run it on the public log."""
import json

from calibration_log.cli import main
from calibration_log.log import CalibrationLog


def _track(tmp_path):
    p = tmp_path / "t.jsonl"
    log = CalibrationLog(p)
    log.predict("rain by friday", 0.6, "2099-01-01")  # future deadline -> not stale
    log.resolve("p1", "yes")
    return p


def test_verify_clean_exits_zero(tmp_path, capsys):
    p = _track(tmp_path)
    rc = main(["verify", "--log", str(p)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "VERIFIED" in out
    assert "intact" in out


def test_verify_detects_tamper_exits_one(tmp_path, capsys):
    p = _track(tmp_path)
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    rows[0]["event_data"]["prob"] = 0.99  # edit a sealed past entry -> breaks the hash
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    rc = main(["verify", "--log", str(p)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "GATE FAILED" in out


def test_verify_missing_track_exits_two(tmp_path, capsys):
    rc = main(["verify", "--log", str(tmp_path / "nope.jsonl")])
    assert rc == 2
    assert "no chain" in capsys.readouterr().err


def test_verify_json_shape(tmp_path, capsys):
    p = _track(tmp_path)
    rc = main(["verify", "--log", str(p), "--json"])
    obj = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert obj["ok"] is True
    assert set(obj) >= {"track", "ok", "score", "findings"}
