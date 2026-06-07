"""Tests for the reconcile mechanism — the anti-cherry-pick / anti-doctoring proof.

These pin the three doctoring vectors the README claims to prevent (MISSING /
FLIPPED / EXTRA), the track parser (keys on the stable `src`), the source loader's
three accepted formats, and an end-to-end check that a hidden loss is caught.
"""
import json

from calibration_log.audit import AuditChain
from calibration_log.reconcile import load_source, published_resolved, reconcile


# ── reconcile() core — the three doctoring vectors ───────────────────

def test_clean_reconcile_passes():
    r = reconcile({"t1": 1, "t2": 0}, {"t1": 1, "t2": 0})
    assert r.ok and r.matched == 2
    assert not r.missing and not r.flipped and not r.extra


def test_missing_fails():
    # source recorded a resolved item the track omits (a hidden loss = cherry-picking)
    r = reconcile({"t1": 1}, {"t1": 1, "t2": 0})
    assert not r.ok
    assert r.missing == {"t2": 0}


def test_flipped_fails():
    # published outcome doctored vs what the source recorded
    r = reconcile({"t1": 1}, {"t1": 0})
    assert not r.ok
    assert r.flipped == {"t1": {"published": 1, "source": 0}}


def test_extra_fails():
    # published an outcome the source never recorded (fabricated)
    r = reconcile({"t1": 1, "t2": 1}, {"t1": 1})
    assert not r.ok
    assert r.extra == {"t2": 1}


def test_summary_strings():
    assert "reconciled" in reconcile({"t1": 1}, {"t1": 1}).summary()
    assert "FAILED" in reconcile({}, {"t1": 0}).summary()


# ── published_resolved() — parse a real track, key on src ────────────

def _write_track(path):
    ch = AuditChain(path)
    ch.append("predict", {"id": "p1", "claim": "c1", "prob": 0.6, "by": "x", "src": "t1"}, "yggdrasil")
    ch.append("resolve", {"id": "p1", "outcome": 0, "src": "t1"}, "yggdrasil")
    ch.append("predict", {"id": "p2", "claim": "c2", "prob": 0.4, "by": "x", "src": "t2"}, "yggdrasil")
    ch.append("resolve", {"id": "p2", "outcome": 1, "src": "t2"}, "yggdrasil")
    ch.append("predict", {"id": "p3", "claim": "c3", "prob": 0.5, "by": "x", "src": "t3"}, "yggdrasil")  # open


def test_published_resolved_keys_on_src(tmp_path):
    p = tmp_path / "track.jsonl"
    _write_track(p)
    assert published_resolved(p) == {"t1": 0, "t2": 1}  # p3 is open -> excluded


def test_published_resolved_falls_back_to_pid(tmp_path):
    p = tmp_path / "track.jsonl"
    ch = AuditChain(p)
    ch.append("predict", {"id": "p1", "claim": "c", "prob": 0.6, "by": "x"}, "y")  # no src
    ch.append("resolve", {"id": "p1", "outcome": 1}, "y")
    assert published_resolved(p) == {"p1": 1}


# ── load_source() — all three accepted formats ───────────────────────

def test_load_source_object(tmp_path):
    p = tmp_path / "src.json"
    p.write_text(json.dumps({"t1": 1, "t2": 0}))
    assert load_source(p) == {"t1": 1, "t2": 0}


def test_load_source_list(tmp_path):
    p = tmp_path / "src.json"
    p.write_text(json.dumps([{"src": "t1", "outcome": 1}, {"src": "t2", "outcome": 0}]))
    assert load_source(p) == {"t1": 1, "t2": 0}


def test_load_source_jsonl(tmp_path):
    p = tmp_path / "src.jsonl"
    p.write_text('{"src": "t1", "outcome": 1}\n{"src": "t2", "outcome": 0}\n')
    assert load_source(p) == {"t1": 1, "t2": 0}


def test_load_source_empty(tmp_path):
    p = tmp_path / "src.json"
    p.write_text("")
    assert load_source(p) == {}


# ── end-to-end: a hidden loss is caught ──────────────────────────────

def test_end_to_end_hidden_loss_is_caught(tmp_path):
    track = tmp_path / "track.jsonl"
    _write_track(track)  # publishes t1->0, t2->1

    honest = tmp_path / "honest.json"
    honest.write_text(json.dumps({"t1": 0, "t2": 1}))
    assert reconcile(published_resolved(track), load_source(honest)).ok

    # the live system actually resolved t9 as a loss, but the track hides it
    cherry_picked = tmp_path / "hidden.json"
    cherry_picked.write_text(json.dumps({"t1": 0, "t2": 1, "t9": 0}))
    r = reconcile(published_resolved(track), load_source(cherry_picked))
    assert not r.ok and r.missing == {"t9": 0}
