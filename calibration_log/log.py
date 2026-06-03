"""The calibration log — append-only, hash-chained predictions, scored over time.

A *prediction* is logged before the fact with a probability in (0, 1) and a
resolution date. Resolving it appends an outcome. The Brier score (mean squared
error of probability vs. outcome; lower is better) and a calibration table
(predicted vs. actual frequency) are computed from the chain.
"""
from __future__ import annotations

from pathlib import Path

from .audit import AuditChain

_TRUTHY = {"yes", "y", "true", "t", "1", "hit"}
_FALSY = {"no", "n", "false", "f", "0", "miss"}


class CalibrationLog:
    def __init__(self, path: str | Path = "predictions.jsonl") -> None:
        self.chain = AuditChain(path)

    def _events(self) -> list[dict]:
        return self.chain.read()

    def predictions(self) -> dict:
        return {e["event_data"]["id"]: e["event_data"]
                for e in self._events() if e["event_type"] == "predict"}

    def resolutions(self) -> dict:
        return {e["event_data"]["id"]: e["event_data"]["outcome"]
                for e in self._events() if e["event_type"] == "resolve"}

    def predict(self, claim: str, prob: float, by: str, actor: str = "operator") -> dict:
        prob = float(prob)
        if not 0.0 < prob < 1.0:
            raise ValueError("probability must be in (0, 1), exclusive")
        pid = f"p{len(self.predictions()) + 1}"
        return self.chain.append(
            "predict", {"id": pid, "claim": claim, "prob": round(prob, 4), "by": str(by)}, actor)

    def resolve(self, pid: str, outcome, actor: str = "operator") -> dict:
        if pid not in self.predictions():
            raise KeyError(f"unknown prediction {pid!r}")
        if pid in self.resolutions():
            raise ValueError(f"{pid} already resolved")
        s = str(outcome).strip().lower()
        if s in _TRUTHY:
            o = 1
        elif s in _FALSY:
            o = 0
        else:
            raise ValueError(f"outcome must be yes/no, got {outcome!r}")
        return self.chain.append("resolve", {"id": pid, "outcome": o}, actor)

    def score(self) -> dict:
        preds, res = self.predictions(), self.resolutions()
        resolved = [(preds[i]["prob"], res[i]) for i in preds if i in res]
        n = len(resolved)
        brier = round(sum((p - o) ** 2 for p, o in resolved) / n, 4) if n else None
        buckets = []
        for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
            hi = lo + 0.2
            grp = [(p, o) for p, o in resolved if lo <= p < hi]
            if grp:
                buckets.append({
                    "range": f"{lo:.1f}-{hi:.1f}",
                    "pred": round(sum(p for p, _ in grp) / len(grp), 3),
                    "actual": round(sum(o for _, o in grp) / len(grp), 3),
                    "n": len(grp)})
        ok, msg = self.chain.verify()
        return {"total": len(preds), "resolved": n, "pending": len(preds) - n,
                "brier": brier, "buckets": buckets, "chain_ok": ok, "chain_msg": msg}

    def render(self) -> str:
        s = self.score()
        preds, res = self.predictions(), self.resolutions()
        chain = "intact ✓" if s["chain_ok"] else f"BROKEN — {s['chain_msg']}"
        out = ["# Calibration scoreboard", "",
               f"_{s['total']} predictions · {s['resolved']} resolved · "
               f"{s['pending']} open · chain {chain}_", ""]
        if s["brier"] is not None:
            out.append(f"**Brier score: {s['brier']}** — lower is better "
                       f"(0.25 = no skill, 0.0 = perfect)")
        else:
            out.append("_No resolved predictions yet — the Brier score appears "
                       "once you resolve one._")
        out.append("")
        if s["buckets"]:
            out += ["## Calibration", "",
                    "| range | avg predicted | actual freq | n |", "|---|---|---|---|"]
            out += [f"| {b['range']} | {b['pred']} | {b['actual']} | {b['n']} |"
                    for b in s["buckets"]]
            out.append("")
        openp = [p for i, p in preds.items() if i not in res]
        if openp:
            out += ["## Open", ""]
            out += [f"- **{p['id']}** — {p['claim']} — _p={p['prob']}, by {p['by']}_"
                    for p in openp]
            out.append("")
        donep = [(i, preds[i], res[i]) for i in preds if i in res]
        if donep:
            out += ["## Resolved", ""]
            for i, p, o in donep:
                hit = (o == 1) == (p["prob"] >= 0.5)
                out.append(f"- **{i}** — {p['claim']} — _p={p['prob']} → "
                           f"{'YES' if o else 'NO'}_ {'✓' if hit else '✗'} "
                           f"(brier {round((p['prob'] - o) ** 2, 3)})")
            out.append("")
        out.append("_Generated from `predictions.jsonl` (append-only, hash-chained). "
                   "Re-run `calibration-log render`._")
        return "\n".join(out)
