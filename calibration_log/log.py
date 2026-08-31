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

    def voids(self) -> dict:
        """``{id: reason}`` for predictions retracted before any outcome was known."""
        return {e["event_data"]["id"]: e["event_data"]["reason"]
                for e in self._events() if e["event_type"] == "void"}

    def live_predictions(self) -> dict:
        """Predictions that still count — everything except the voided."""
        voided = self.voids()
        return {i: d for i, d in self.predictions().items() if i not in voided}

    def predict(self, claim: str, prob: float, by: str, actor: str = "operator",
                src: str | None = None) -> dict:
        prob = float(prob)
        if not 0.0 < prob < 1.0:
            raise ValueError("probability must be in (0, 1), exclusive")
        pid = f"p{len(self.predictions()) + 1}"
        data = {"id": pid, "claim": claim, "prob": round(prob, 4), "by": str(by)}
        if src:
            # a stable id from outside this log, so re-presenting the same prediction
            # (a `git commit --amend`, a hook run twice) is refused rather than duplicated
            data["src"] = str(src)
        return self.chain.append("predict", data, actor)

    def sources(self) -> set:
        """Every external ``src`` already registered on this chain."""
        return {d["src"] for d in self.predictions().values() if d.get("src")}

    def void(self, pid: str, reason: str, actor: str = "operator") -> dict:
        """Retract an OPEN prediction, without deleting anything.

        An append-only chain cannot be rewritten, which is the property that makes it
        worth trusting — but it still needs a way to say "this entry was never a real
        claim". A parser bug that registers junk, or a duplicate, would otherwise sit
        in the record forever, unresolvable except by inventing an outcome for it.

        The abuse this obviously invites is voiding the predictions you lost, so the
        rule is narrow and absolute: **a resolved prediction can never be voided.** A
        loss is by definition resolved, so there is no path from a bad outcome to a
        clean record. Retracting a claim *before* the outcome is known is legitimate,
        and voiding writes a new event with a reason rather than removing the old one —
        the retraction is as permanent and as public as the claim was.
        """
        if pid not in self.predictions():
            raise KeyError(f"unknown prediction {pid!r}")
        if pid in self.resolutions():
            raise ValueError(
                f"{pid} is resolved — a resolved prediction can never be voided")
        if pid in self.voids():
            raise ValueError(f"{pid} already voided")
        if not str(reason).strip():
            raise ValueError("voiding requires a reason — an unexplained retraction "
                             "is indistinguishable from hiding one")
        return self.chain.append("void", {"id": pid, "reason": str(reason).strip()}, actor)

    def resolve(self, pid: str, outcome, actor: str = "operator") -> dict:
        if pid not in self.predictions():
            raise KeyError(f"unknown prediction {pid!r}")
        if pid in self.voids():
            raise ValueError(f"{pid} was voided and cannot be resolved")
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
        preds, res = self.live_predictions(), self.resolutions()
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
                "voided": len(self.voids()),
                "brier": brier, "buckets": buckets, "chain_ok": ok, "chain_msg": msg}

    def render(self) -> str:
        s = self.score()
        preds, res, voided = self.live_predictions(), self.resolutions(), self.voids()
        chain = "intact ✓" if s["chain_ok"] else f"BROKEN — {s['chain_msg']}"
        head = (f"_{s['total']} predictions · {s['resolved']} resolved · "
                f"{s['pending']} open")
        if voided:
            head += f" · {len(voided)} voided"
        out = ["# Calibration scoreboard", "", head + f" · chain {chain}_", ""]
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
        if voided:
            # shown, never hidden: a retraction is as public as the claim it retracts
            allp = self.predictions()
            out += ["## Voided", "",
                    "_Retracted before any outcome was known, and excluded from the "
                    "score. A resolved prediction can never be voided._", ""]
            out += [f"- **{i}** — {allp[i]['claim']} — _p={allp[i]['prob']}_ — "
                    f"voided: {r}" for i, r in voided.items()]
            out.append("")
        out.append("_Generated from an append-only, hash-chained log._")
        return "\n".join(out)
