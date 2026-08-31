"""The side-effect feed: commit-message trailers -> the chain.

The failure this mechanism exists to prevent is a prediction that is *written down and
then lost*. So the tests weight two things above all: a malformed trailer is reported
rather than silently dropped, and registering the same prediction twice is a no-op.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from calibration_log.cli import HOOK_MARK, main
from calibration_log.log import CalibrationLog
from calibration_log.trailer import parse, source_id


# ------------------------------------------------------------------ parsing

def test_parses_decimal_and_percent_the_same():
    p = parse("work\n\nPredict: 0.70 2026-12-31 a\nPredict: 70% 2026-12-31 b\n")
    assert [x.prob for x in p.predictions] == [0.7, 0.7]


def test_claim_keeps_its_whole_line():
    p = parse("Predict: 0.6 2026-11-30 the wired edge count is still exactly 17")
    assert p.predictions[0].claim == "the wired edge count is still exactly 17"
    assert p.predictions[0].by == "2026-11-30"


def test_malformed_trailer_is_an_error_not_a_silent_drop():
    # the whole point: an intended prediction must never vanish quietly
    p = parse("Predict: sometime soon, probably")
    assert not p.predictions
    assert any("malformed" in e for e in p.errors)


def test_out_of_range_probability_is_rejected_with_its_claim():
    p = parse("Predict: 1.5 2026-12-31 certainty is not a prediction")
    assert not p.predictions
    assert "certainty is not a prediction" in p.errors[0]


def test_impossible_date_is_rejected():
    p = parse("Predict: 0.5 2026-13-45 bad date")
    assert not p.predictions and p.errors


def test_a_prose_mention_of_predict_is_not_a_trailer():
    p = parse("I predict: this will not parse as a trailer because it is prose.")
    assert not p.predictions and not p.errors


def test_verified_block_without_a_trailer_is_flagged():
    p = parse("fix\n\nVERIFIED — tested, 65 green\n")
    assert p.verified and p.uncalibrated


def test_verified_block_with_a_trailer_is_not_flagged():
    p = parse("fix\n\nPredict: 0.7 2026-12-31 x\n\nVERIFIED — tested\n")
    assert p.verified and not p.uncalibrated


def test_no_verified_block_is_never_flagged():
    # most commits make no claim of doneness; silence is correct there
    assert not parse("routine cleanup").uncalibrated


def test_source_id_is_content_addressed_not_commit_addressed():
    # `git commit --amend` gives a new SHA for the same prediction, so the id must
    # come from the content or an amend would register it a second time
    a = source_id(0.7, "2026-12-31", "same claim", "repo")
    b = source_id(0.7, "2026-12-31", "  same claim  ", "repo")
    c = source_id(0.7, "2026-12-31", "different", "repo")
    assert a == b and a != c


def test_label_scopes_the_id():
    assert source_id(0.7, "2026-12-31", "x", "a") != source_id(0.7, "2026-12-31", "x", "b")


# ------------------------------------------------------------------ ingest

@pytest.fixture
def feed(tmp_path, monkeypatch):
    """An isolated calibration-log tree, so tests never touch the real chain."""
    import calibration_log.cli as cli
    root = tmp_path / "log"
    (root / "tracks").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(cli, "LOG", root / "predictions.jsonl")
    monkeypatch.setattr(cli, "BOARD", root / "SCOREBOARD.md")
    return root


def _stdin(monkeypatch, text):
    import io
    buf = io.StringIO(text)
    buf.isatty = lambda: False
    monkeypatch.setattr(sys, "stdin", buf)


def test_ingest_registers_a_trailer_onto_a_track(feed, monkeypatch, capsys):
    _stdin(monkeypatch, "work\n\nPredict: 0.7 2026-12-31 the claim\n")
    assert main(["ingest", "--track", "t", "--label", "repo"]) == 0
    log = CalibrationLog(feed / "tracks" / "t.jsonl")
    (p,) = log.predictions().values()
    assert p["prob"] == 0.7 and p["claim"] == "the claim"
    assert p["src"].startswith("repo:")


def test_ingest_is_idempotent(feed, monkeypatch, capsys):
    msg = "work\n\nPredict: 0.7 2026-12-31 the claim\n"
    for _ in range(3):
        _stdin(monkeypatch, msg)
        main(["ingest", "--track", "t", "--label", "repo"])
    assert len(CalibrationLog(feed / "tracks" / "t.jsonl").predictions()) == 1
    assert "already registered" in capsys.readouterr().out


def test_ingest_never_fails_a_commit_by_default(feed, monkeypatch):
    _stdin(monkeypatch, "Predict: garbage\n")
    assert main(["ingest", "--track", "t"]) == 0


def test_ingest_can_be_strict_when_asked(feed, monkeypatch):
    _stdin(monkeypatch, "Predict: garbage\n")
    assert main(["ingest", "--track", "t", "--strict"]) == 1


def test_dry_run_writes_nothing(feed, monkeypatch):
    _stdin(monkeypatch, "Predict: 0.7 2026-12-31 the claim\n")
    main(["ingest", "--track", "t", "--dry-run"])
    assert not (feed / "tracks" / "t.jsonl").exists()


def test_empty_message_is_a_no_op(feed, monkeypatch):
    _stdin(monkeypatch, "   \n")
    assert main(["ingest", "--track", "t"]) == 0
    assert not (feed / "tracks" / "t.jsonl").exists()


# ------------------------------------------------------------------ hook

@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    return r


def test_install_writes_an_executable_hook(repo, capsys):
    assert main(["hook", "install", "--repo", str(repo), "--track", "t"]) == 0
    h = repo / ".git" / "hooks" / "post-commit"
    assert h.exists() and h.stat().st_mode & 0o111
    body = h.read_text()
    assert HOOK_MARK in body and "CALIBRATION_LOG_SKIP" in body and "exit 0" in body


def test_install_refuses_to_clobber_someone_elses_hook(repo, capsys):
    h = repo / ".git" / "hooks" / "post-commit"
    h.write_text("#!/bin/sh\necho mine\n")
    assert main(["hook", "install", "--repo", str(repo)]) == 2
    assert h.read_text() == "#!/bin/sh\necho mine\n"


def test_uninstall_refuses_to_remove_someone_elses_hook(repo):
    h = repo / ".git" / "hooks" / "post-commit"
    h.write_text("#!/bin/sh\necho mine\n")
    assert main(["hook", "uninstall", "--repo", str(repo)]) == 2
    assert h.exists()


def test_reinstall_over_our_own_hook_is_allowed(repo):
    main(["hook", "install", "--repo", str(repo)])
    assert main(["hook", "install", "--repo", str(repo), "--track", "t2"]) == 0
    assert '--track "t2"' in (repo / ".git" / "hooks" / "post-commit").read_text()


def test_status_reports_absent_then_present(repo):
    assert main(["hook", "status", "--repo", str(repo)]) == 1
    main(["hook", "install", "--repo", str(repo)])
    assert main(["hook", "status", "--repo", str(repo)]) == 0


# --------------------------------------------- regression: the example-in-prose bug

def test_an_indented_example_is_not_a_prediction():
    """Shipped, live, on this mechanism's own first real commit.

    The message explained the feature and included an indented sample trailer. The
    parser matched it and registered a prediction whose claim was `<claim>`. This is
    the import resolver's string-literal defect in a different costume: text that looks
    like a directive but sits inside a quotation. Git trailers live at column 0, and
    every way of quoting one puts something in front of it.
    """
    msg = (
        "feed the log as a side effect of committing\n\n"
        "Registration moves onto the commit message:\n\n"
        "    Predict: 0.70 2026-12-31 <claim>\n\n"
        "A post-commit hook reads it.\n\n"
        "Predict: 0.45 2026-12-31 the real claim\n"
    )
    p = parse(msg)
    assert [x.claim for x in p.predictions] == ["the real claim"]
    assert not p.errors


def test_a_quoted_or_fenced_trailer_is_not_a_prediction():
    for quoted in ("> Predict: 0.7 2026-12-31 x", "\tPredict: 0.7 2026-12-31 x",
                   "  Predict: 0.7 2026-12-31 x", "# Predict: 0.7 2026-12-31 x"):
        p = parse(f"work\n\n{quoted}\n")
        assert not p.predictions and not p.errors, quoted


# ------------------------------------------------- void: retraction without deletion

def test_voiding_an_open_prediction_removes_it_from_the_score(tmp_path):
    log = CalibrationLog(tmp_path / "c.jsonl")
    log.predict("junk from a parser bug", 0.7, "2026-12-31")
    log.predict("a real claim", 0.45, "2026-12-31")
    log.void("p1", "parser matched an indented example in the commit prose")
    assert log.score()["total"] == 1
    assert log.score()["voided"] == 1
    assert list(log.live_predictions()) == ["p2"]


def test_a_void_is_appended_never_deleted(tmp_path):
    path = tmp_path / "c.jsonl"
    log = CalibrationLog(path)
    log.predict("junk", 0.7, "2026-12-31")
    before = path.read_text()
    log.void("p1", "never a real claim")
    after = path.read_text()
    assert after.startswith(before)          # the original entry is untouched
    assert log.score()["chain_ok"]           # and the chain still verifies
    assert "p1" in log.predictions()         # still readable, just not scored


def test_a_resolved_prediction_can_never_be_voided(tmp_path):
    """The anti-cherry-pick rule. A loss is by definition resolved, so there is no
    path from a bad outcome to a clean record."""
    log = CalibrationLog(tmp_path / "c.jsonl")
    log.predict("a claim that will lose", 0.9, "2026-12-31")
    log.resolve("p1", "no")
    with pytest.raises(ValueError, match="can never be voided"):
        log.void("p1", "I would rather this had not happened")
    assert log.score()["brier"] is not None   # the loss still counts


def test_a_voided_prediction_cannot_be_resolved(tmp_path):
    log = CalibrationLog(tmp_path / "c.jsonl")
    log.predict("junk", 0.7, "2026-12-31")
    log.void("p1", "parser artifact")
    with pytest.raises(ValueError, match="voided"):
        log.resolve("p1", "yes")


def test_voiding_requires_a_reason(tmp_path):
    log = CalibrationLog(tmp_path / "c.jsonl")
    log.predict("x", 0.7, "2026-12-31")
    for empty in ("", "   "):
        with pytest.raises(ValueError, match="requires a reason"):
            log.void("p1", empty)


def test_voiding_twice_is_refused(tmp_path):
    log = CalibrationLog(tmp_path / "c.jsonl")
    log.predict("x", 0.7, "2026-12-31")
    log.void("p1", "once")
    with pytest.raises(ValueError, match="already voided"):
        log.void("p1", "twice")


def test_the_scoreboard_shows_voided_entries_rather_than_hiding_them(tmp_path):
    log = CalibrationLog(tmp_path / "c.jsonl")
    log.predict("junk from a parser bug", 0.7, "2026-12-31")
    log.void("p1", "matched an indented example")
    md = log.render()
    assert "## Voided" in md
    assert "junk from a parser bug" in md
    assert "matched an indented example" in md


def test_void_via_the_cli_commits_and_rescores(feed, capsys):
    main(["predict", "junk", "--prob", "0.7", "--by", "2026-12-31", "--track", "t"])
    assert main(["void", "p1", "--reason", "parser artifact", "--track", "t"]) == 0
    assert CalibrationLog(feed / "tracks" / "t.jsonl").score()["total"] == 0
    assert "## Voided" in (feed / "tracks" / "T.md").read_text()
