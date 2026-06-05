"""Governor for the calibration feed — turn a score into a pass/fail verdict.

``log.py`` proves a record is *tamper-evident*. The governor judges whether the
record is *honest to look at*: the chain is intact, the track is not quietly
stale, and a suspiciously-good hit-rate is **flagged as auto-suspect** rather than
bragged about.

This is the operator discipline, mechanized. Per the operator protocol a
``>65%`` win-rate is "auto-suspect — a bug to disprove", not a win to claim; the
governor surfaces it as a finding so a too-good record can never quietly pass as
a brag. The functions are pure (score + events in, findings out), so the CLI, a
scheduled check, and the tests all share one source of truth for the verdict.
"""
from __future__ import annotations

from datetime import datetime, timezone

# OPERATOR_PROTOCOL red line: a win-rate above this is a bug to disprove, not a win.
AUTO_SUSPECT_HIT_RATE = 0.65
# A Brier this low over a non-trivial sample is implausibly good — check for look-ahead.
SUSPECT_BRIER = 0.05
# Don't cry "suspect" on a handful of resolutions — small samples swing wildly.
MIN_N_FOR_SUSPECT = 5


def hit_rate(resolved: list[tuple[float, int]]) -> float | None:
    """Fraction of resolved predictions whose stated side won.

    ``resolved`` is a list of ``(prob, outcome)``. The stated side is YES when
    ``prob >= 0.5``; it "won" when the outcome matches. Returns ``None`` for an
    empty list (no claim to grade).
    """
    if not resolved:
        return None
    hits = sum(1 for p, o in resolved if (o == 1) == (p >= 0.5))
    return hits / len(resolved)


def _parse_iso(s) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def overdue(predictions: dict, resolutions: dict, now: datetime) -> list[str]:
    """Prediction ids whose ``by`` deadline has passed but are still unresolved.

    An honest feed resolves on time; overdue items are how a feed quietly stalls
    (predictions made, outcomes never recorded — the record stops being current).
    """
    out = []
    for pid, pd in predictions.items():
        if pid in resolutions:
            continue
        by = _parse_iso(pd.get("by"))
        if by is not None and by < now:
            out.append(pid)
    return out


def govern(
    score: dict,
    resolved_pairs: list[tuple[float, int]],
    predictions: dict,
    resolutions: dict,
    now: datetime,
    *,
    strict: bool = False,
) -> tuple[list[dict], bool]:
    """Judge a track. Returns ``(findings, ok)``.

    Each finding is ``{level, code, msg}``. ``ok`` is the gate verdict:
      * a BROKEN chain always fails (the non-negotiable);
      * SUSPECT / STALE findings fail only under ``strict`` (otherwise they are
        surfaced as warnings but don't sink the gate — the chain is what's
        cryptographically guaranteed, the rest is judgment to act on).
    """
    findings: list[dict] = []
    hard_fail = False

    # 1. Chain integrity — the non-negotiable, cryptographic guarantee.
    if not score.get("chain_ok"):
        findings.append({
            "level": "FAIL", "code": "chain_broken",
            "msg": f"audit chain BROKEN — {score.get('chain_msg')}",
        })
        hard_fail = True

    n = len(resolved_pairs)

    # 2. Auto-suspect — a too-good record is a bug to disprove (protocol red line).
    hr = hit_rate(resolved_pairs)
    if hr is not None and n >= MIN_N_FOR_SUSPECT and hr > AUTO_SUSPECT_HIT_RATE:
        findings.append({
            "level": "SUSPECT", "code": "hit_rate_auto_suspect",
            "msg": (f"hit-rate {hr:.0%} over {n} resolved exceeds "
                    f"{AUTO_SUSPECT_HIT_RATE:.0%} — auto-suspect: a bug to "
                    f"disprove (look-ahead? leakage?), not a win to claim"),
        })
    brier = score.get("brier")
    if brier is not None and n >= MIN_N_FOR_SUSPECT and brier < SUSPECT_BRIER:
        findings.append({
            "level": "SUSPECT", "code": "brier_too_low",
            "msg": (f"Brier {brier} over {n} resolved is implausibly low "
                    f"(<{SUSPECT_BRIER}) — verify it isn't look-ahead"),
        })

    # 3. Staleness — overdue, unresolved predictions (a feed quietly stalling).
    od = overdue(predictions, resolutions, now)
    if od:
        findings.append({
            "level": "STALE", "code": "overdue_resolutions",
            "msg": (f"{len(od)} prediction(s) past their resolution date and "
                    f"unresolved: {', '.join(od[:8])}{' …' if len(od) > 8 else ''}"),
        })

    ok = not hard_fail
    if strict and any(f["level"] in ("SUSPECT", "STALE") for f in findings):
        ok = False
    return findings, ok
