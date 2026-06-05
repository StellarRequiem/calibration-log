"""calibration-log CLI — predict / resolve / score / render / publish.

Each predict/resolve appends to the hash-chained log, regenerates SCOREBOARD.md,
and commits (the public, timestamped audit trail). `publish` pushes.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .govern import AUTO_SUSPECT_HIT_RATE, govern, hit_rate
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
    vp = sub.add_parser(
        "verify", help="govern a track: chain integrity + auto-suspect + staleness")
    vp.add_argument("--track", help="track under tracks/ (e.g. 'yggdrasil'); default: the main log")
    vp.add_argument("--log", help="explicit path to a predictions.jsonl chain (overrides --track)")
    vp.add_argument("--strict", action="store_true",
                    help="exit non-zero on auto-suspect/staleness too, not just a broken chain")
    vp.add_argument("--json", action="store_true", help="machine-readable verdict")
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
        elif args.cmd == "verify":
            return _verify(args)
    except (ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


def _verify(args) -> int:
    """Govern a track and print the verdict. Exit 0 iff it passes the gate
    (a broken chain always fails; --strict also fails on auto-suspect/staleness)."""
    if args.log:
        path = Path(args.log)
    elif args.track:
        path = ROOT / "tracks" / f"{args.track}.jsonl"
    else:
        path = LOG
    if not path.exists():
        print(f"error: no chain at {path}", file=sys.stderr)
        return 2

    log = CalibrationLog(path)
    s = log.score()
    preds, res = log.predictions(), log.resolutions()
    resolved_pairs = [(preds[i]["prob"], res[i]) for i in preds if i in res]
    now = datetime.now(timezone.utc)
    findings, ok = govern(s, resolved_pairs, preds, res, now, strict=args.strict)

    if args.json:
        print(json.dumps({"track": path.name, "ok": ok, "score": s,
                          "findings": findings}, indent=2))
        return 0 if ok else 1

    hr = hit_rate(resolved_pairs)
    chain = "intact ✓" if s["chain_ok"] else f"BROKEN — {s['chain_msg']}"
    print(f"calibration feed — {path.name}")
    print("=" * 44)
    print(f"  chain     : {chain}")
    print(f"  record    : {s['total']} predictions · {s['resolved']} resolved · "
          f"{s['pending']} open")
    print(f"  brier     : {s['brier'] if s['brier'] is not None else 'n/a'}  "
          f"(0.25 = no skill, 0 = perfect)")
    print(f"  hit-rate  : {f'{hr:.0%}' if hr is not None else 'n/a'}  "
          f"(auto-suspect above {AUTO_SUSPECT_HIT_RATE:.0%})")
    if findings:
        print("\n  findings:")
        for f in findings:
            print(f"    [{f['level']}] {f['msg']}")
    else:
        print("\n  findings: none — chain intact, not auto-suspect, current")
    print()
    print("VERIFIED — feed governed, no hard failure" if ok
          else "GATE FAILED — see findings above")
    return 0 if ok else 1
