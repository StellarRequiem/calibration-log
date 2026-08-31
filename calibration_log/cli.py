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
from .reconcile import load_source, published_resolved, reconcile
from .trailer import parse as parse_trailers

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "predictions.jsonl"
BOARD = ROOT / "SCOREBOARD.md"


def _feed(track: str | None) -> tuple[Path, Path]:
    """Resolve a feed name to its chain and its board.

    `verify` and `reconcile` already accepted `--track`, but `predict`, `resolve` and
    `score` did not — a track could be governed and never written to, so anything not
    belonging in the main record had no way in. Every command takes the same option
    now, and the main log stays the default.
    """
    if not track:
        return LOG, BOARD
    return ROOT / "tracks" / f"{track}.jsonl", ROOT / "tracks" / f"{track.upper()}.md"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def _render(log: CalibrationLog, board: Path = BOARD) -> None:
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_text(log.render() + "\n", encoding="utf-8")


def _commit(msg: str, *paths: Path) -> None:
    rel = [str(p.relative_to(ROOT)) for p in (paths or (LOG, BOARD))]
    _git("add", *rel)
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
    pp.add_argument("--track", help="track under tracks/; default: the main log")
    rr = sub.add_parser("resolve", help="resolve a prediction")
    rr.add_argument("id")
    rr.add_argument("outcome", help="yes | no")
    rr.add_argument("--track", help="track under tracks/; default: the main log")
    sc = sub.add_parser("score", help="print the scoreboard")
    sc.add_argument("--track", help="track under tracks/; default: the main log")
    sub.add_parser("render", help="(re)write SCOREBOARD.md")
    sub.add_parser("publish", help="git push the log")
    vp = sub.add_parser(
        "verify", help="govern a track: chain integrity + auto-suspect + staleness")
    vp.add_argument("--track", help="track under tracks/ (e.g. 'yggdrasil'); default: the main log")
    vp.add_argument("--log", help="explicit path to a predictions.jsonl chain (overrides --track)")
    vp.add_argument("--strict", action="store_true",
                    help="exit non-zero on auto-suspect/staleness too, not just a broken chain")
    vp.add_argument("--json", action="store_true", help="machine-readable verdict")
    rc = sub.add_parser(
        "reconcile",
        help="prove a published track matches its live source (no cherry-picking / doctoring)")
    rc.add_argument("--source", required=True,
                    help="operator's read-only export of ELIGIBLE RESOLVED outcomes: "
                         "a {src: outcome} JSON object, a list of {src,outcome}, or JSONL")
    rc.add_argument("--track", help="track under tracks/ (e.g. 'yggdrasil'); default: the main log")
    rc.add_argument("--log", help="explicit path to a track chain (overrides --track)")
    rc.add_argument("--json", action="store_true", help="machine-readable verdict")
    ig = sub.add_parser(
        "ingest",
        help="register `Predict:` trailers read from a commit message on stdin")
    ig.add_argument("--track", help="track under tracks/; default: the main log")
    ig.add_argument("--label", default="",
                    help="short name for where this came from, e.g. the repo name")
    ig.add_argument("--dry-run", action="store_true", help="report, write nothing")
    ig.add_argument("--strict", action="store_true",
                    help="exit non-zero on a malformed trailer; off by default so a "
                         "hook can never fail a commit")
    hk = sub.add_parser(
        "hook", help="install the post-commit hook that feeds this log as a side effect")
    hk.add_argument("action", choices=["install", "status", "uninstall"])
    hk.add_argument("--repo", required=True, help="path to the git repository")
    hk.add_argument("--track", help="track under tracks/; default: the main log")
    hk.add_argument("--label", help="label for ids; default: the repo directory name")
    args = ap.parse_args(argv)

    chain, board = _feed(getattr(args, "track", None))
    log = CalibrationLog(chain)
    try:
        if args.cmd == "predict":
            e = log.predict(args.claim, args.prob, args.by)
            pid = e["event_data"]["id"]
            _render(log, board)
            _commit(f"predict {pid}: {args.claim[:60]} (p={args.prob})", chain, board)
            print(f"logged {pid}: {args.claim!r}  p={args.prob}  by {args.by}")
        elif args.cmd == "resolve":
            e = log.resolve(args.id, args.outcome)
            o = e["event_data"]["outcome"]
            _render(log, board)
            _commit(f"resolve {args.id}: {'yes' if o else 'no'}", chain, board)
            print(f"resolved {args.id} -> {'YES' if o else 'NO'}")
        elif args.cmd == "score":
            print(log.render())
        elif args.cmd == "render":
            _render(log, board)
            print(f"wrote {board.name}")
        elif args.cmd == "publish":
            r = _git("push", "origin", "HEAD")
            print((r.stdout + r.stderr).strip() or "pushed")
        elif args.cmd == "verify":
            return _verify(args)
        elif args.cmd == "reconcile":
            return _reconcile(args)
        elif args.cmd == "ingest":
            return _ingest(args, log, chain, board)
        elif args.cmd == "hook":
            return _hook(args)
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


def _reconcile(args) -> int:
    """Reconcile a published track against the operator's live-source export.

    Exit 0 iff every eligible resolved source item is published with the same
    outcome — no MISSING (cherry-picked), FLIPPED (doctored), or EXTRA (fabricated)."""
    if args.log:
        path = Path(args.log)
    elif args.track:
        path = ROOT / "tracks" / f"{args.track}.jsonl"
    else:
        path = LOG
    if not path.exists():
        print(f"error: no chain at {path}", file=sys.stderr)
        return 2
    src_path = Path(args.source)
    if not src_path.exists():
        print(f"error: no source export at {src_path}", file=sys.stderr)
        return 2

    pub = published_resolved(path)
    src = load_source(src_path)
    r = reconcile(pub, src)

    if args.json:
        print(json.dumps({"track": path.name, "ok": r.ok, "matched": r.matched,
                          "missing": r.missing, "flipped": r.flipped, "extra": r.extra}, indent=2))
        return 0 if r.ok else 1

    print(f"reconcile — {path.name} vs {src_path.name}")
    print("=" * 44)
    print(f"  published resolved : {len(pub)}")
    print(f"  source resolved    : {len(src)}")
    print(f"  matched            : {r.matched}")
    if r.missing:
        print("\n  MISSING (source recorded, not published — cherry-picked):")
        for k, o in sorted(r.missing.items()):
            print(f"    {k} -> {'YES' if o else 'NO'}")
    if r.flipped:
        print("\n  FLIPPED (published outcome != source — doctored):")
        for k, d in sorted(r.flipped.items()):
            print(f"    {k}: published {'YES' if d['published'] else 'NO'} "
                  f"vs source {'YES' if d['source'] else 'NO'}")
    if r.extra:
        print("\n  EXTRA (published, source never recorded — fabricated):")
        for k, o in sorted(r.extra.items()):
            print(f"    {k} -> {'YES' if o else 'NO'}")
    print()
    print("VERIFIED — " + r.summary() if r.ok else "GATE FAILED — " + r.summary())
    return 0 if r.ok else 1


# ---------------------------------------------------------------- side-effect feed

HOOK_MARK = "# calibration-log post-commit feed"

HOOK_TEMPLATE = """#!/bin/sh
{mark}
# Registers any `Predict: <prob> <YYYY-MM-DD> <claim>` trailer in the commit message
# just written, and notes a VERIFIED block that carries no forward claim.
#
# Deliberately post-commit: it cannot reject or delay a commit. A hook that can fail
# the work gets bypassed and then deleted, and an unfed mechanism is what this exists
# to fix. Every path below ends in `exit 0`.
#
# CALIBRATION_LOG_SKIP breaks the recursion: the ingest below commits to the log, and
# if the log's own repo has this hook installed that commit would re-enter here.
[ -n "$CALIBRATION_LOG_SKIP" ] && exit 0
[ -x "{python}" ] || exit 0
git log -1 --pretty=%B | CALIBRATION_LOG_SKIP=1 "{python}" -m calibration_log ingest {opts} 2>&1 || true
exit 0
"""


def _ingest(args, log, chain, board) -> int:
    """Read a commit message on stdin and register what it predicts.

    Never fails by default. This runs from a git hook, and the contract there is that
    the work always wins: a broken feed must cost a warning, never a commit.
    """
    msg = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not msg.strip():
        return 0

    parsed = parse_trailers(msg, args.label or "")
    known = log.sources() if chain.exists() else set()
    feed = args.track or "main"
    registered, skipped = [], []

    for p in parsed.predictions:
        if p.src in known:
            skipped.append(p)
            continue
        if args.dry_run:
            registered.append((None, p))
            continue
        e = log.predict(p.claim, p.prob, p.by, src=p.src)
        pid = e["event_data"]["id"]
        known.add(p.src)
        registered.append((pid, p))
        _render(log, board)
        _commit(f"predict {pid} [{feed}, via commit trailer]: {p.claim[:60]} (p={p.prob})",
                chain, board)

    for pid, p in registered:
        tag = f"{pid} " if pid else "(dry-run) "
        print(f"calibration-log: registered {tag}p={p.prob} by {p.by} — {p.claim[:70]}")
    for p in skipped:
        print(f"calibration-log: already registered, skipped — {p.claim[:70]}")
    for e in parsed.errors:
        print(f"calibration-log: {e}", file=sys.stderr)
    if parsed.uncalibrated:
        # Criterion 4 of the Standard. Most work honestly makes no predictive claim,
        # so this is a note at the moment doneness is claimed — not a gate. Enforcing
        # a quota would only manufacture filler predictions and a meaningless Brier.
        print("calibration-log: VERIFIED block with no `Predict:` trailer — "
              "criterion 4 (Calibrated) unexercised for this commit", file=sys.stderr)

    return 1 if (args.strict and parsed.errors) else 0


def _hook(args) -> int:
    repo = Path(args.repo).expanduser().resolve()
    hooks = repo / ".git" / "hooks"
    if not hooks.is_dir():
        print(f"error: no .git/hooks in {repo}", file=sys.stderr)
        return 2
    path = hooks / "post-commit"

    if args.action == "status":
        if not path.exists():
            print(f"no post-commit hook in {repo.name}")
            return 1
        mine = HOOK_MARK in path.read_text(encoding="utf-8")
        print(f"{repo.name}: post-commit hook present, "
              f"{'feeds this log ✓' if mine else 'NOT ours — left alone'}")
        return 0 if mine else 1

    if args.action == "uninstall":
        if not path.exists():
            print("nothing installed")
            return 0
        if HOOK_MARK not in path.read_text(encoding="utf-8"):
            print("error: post-commit hook is not ours — refusing to remove it",
                  file=sys.stderr)
            return 2
        path.unlink()
        print(f"removed {path}")
        return 0

    # install — never clobber a hook this tool did not write
    if path.exists() and HOOK_MARK not in path.read_text(encoding="utf-8"):
        print(f"error: {path} already exists and is not ours — refusing to overwrite.\n"
              f"       merge the snippet by hand, or move the existing hook aside.",
              file=sys.stderr)
        return 2

    label = args.label or repo.name
    opts = f'--label "{label}"' + (f' --track "{args.track}"' if args.track else "")
    path.write_text(
        HOOK_TEMPLATE.format(mark=HOOK_MARK, python=sys.executable, opts=opts),
        encoding="utf-8")
    path.chmod(0o755)
    print(f"installed {path}\n"
          f"  label : {label}\n"
          f"  track : {args.track or 'main log'}\n"
          f"  usage : add a line to any commit message —\n"
          f"          Predict: 0.70 2026-12-31 <the claim>")
    return 0
