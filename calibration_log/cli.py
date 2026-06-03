"""calibration-log CLI — predict / resolve / score / render / publish.

Each predict/resolve appends to the hash-chained log, regenerates SCOREBOARD.md,
and commits (the public, timestamped audit trail). `publish` pushes.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .log import CalibrationLog

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "predictions.jsonl"
BOARD = ROOT / "SCOREBOARD.md"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def _render(log: CalibrationLog) -> None:
    BOARD.write_text(log.render() + "\n", encoding="utf-8")


def _commit(msg: str) -> None:
    _git("add", "predictions.jsonl", "SCOREBOARD.md")
    if _git("diff", "--cached", "--quiet").returncode != 0:
        _git("commit", "-q", "-m", msg)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="calibration-log",
        description="A public, hash-chained track record of predictions, scored over time.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("predict", help="log a prediction")
    pp.add_argument("claim")
    pp.add_argument("--prob", type=float, required=True, help="probability in (0,1)")
    pp.add_argument("--by", required=True, help="resolution date, e.g. 2026-08-01")
    rr = sub.add_parser("resolve", help="resolve a prediction")
    rr.add_argument("id")
    rr.add_argument("outcome", help="yes | no")
    sub.add_parser("score", help="print the scoreboard")
    sub.add_parser("render", help="(re)write SCOREBOARD.md")
    sub.add_parser("publish", help="git push the log")
    args = ap.parse_args(argv)

    log = CalibrationLog(LOG)
    try:
        if args.cmd == "predict":
            e = log.predict(args.claim, args.prob, args.by)
            pid = e["event_data"]["id"]
            _render(log)
            _commit(f"predict {pid}: {args.claim[:60]} (p={args.prob})")
            print(f"logged {pid}: {args.claim!r}  p={args.prob}  by {args.by}")
        elif args.cmd == "resolve":
            e = log.resolve(args.id, args.outcome)
            o = e["event_data"]["outcome"]
            _render(log)
            _commit(f"resolve {args.id}: {'yes' if o else 'no'}")
            print(f"resolved {args.id} -> {'YES' if o else 'NO'}")
        elif args.cmd == "score":
            print(log.render())
        elif args.cmd == "render":
            _render(log)
            print(f"wrote {BOARD.name}")
        elif args.cmd == "publish":
            r = _git("push", "origin", "HEAD")
            print((r.stdout + r.stderr).strip() or "pushed")
    except (ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0
