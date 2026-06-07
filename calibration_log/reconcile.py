"""Reconcile a published track against its live source — the anti-cherry-pick proof.

A public track can be quietly doctored three ways:
  - MISSING : a resolved item the source recorded is dropped, so a loss never appears
  - FLIPPED : a published outcome differs from what the source actually recorded
  - EXTRA   : an item is published that the source never recorded (fabricated)

This reconciles the published RESOLVED outcomes against the source's ELIGIBLE
RESOLVED outcomes, both keyed by the stable source id ``src``. A clean reconcile
proves every eligible resolved item is published with the SAME outcome — the
record can only be *completed* over time, never cherry-picked or doctored.

The source is supplied by the operator as a read-only export from the live system
(where its database lives), so this module stays generic and carries no
system-specific schema. See the README "Reconciliation" section for the recipe.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .audit import AuditChain


@dataclass
class Reconciliation:
    ok: bool
    matched: int = 0
    missing: dict = field(default_factory=dict)   # src -> source outcome (published is hiding it)
    flipped: dict = field(default_factory=dict)   # src -> {"published": x, "source": y}
    extra: dict = field(default_factory=dict)     # src -> published outcome (source never recorded it)

    def summary(self) -> str:
        if self.ok:
            return f"reconciled ✓ — {self.matched} resolved items match the source exactly"
        parts = []
        if self.missing:
            parts.append(f"{len(self.missing)} MISSING (recorded by source, not published — cherry-picked)")
        if self.flipped:
            parts.append(f"{len(self.flipped)} FLIPPED (outcome differs from source — doctored)")
        if self.extra:
            parts.append(f"{len(self.extra)} EXTRA (published, not in source — fabricated)")
        return "reconcile FAILED — " + "; ".join(parts)


def reconcile(published: dict, source: dict) -> Reconciliation:
    """Compare two ``{src_id: outcome}`` maps of RESOLVED items. Pure; no I/O.

    published : resolved outcomes parsed from the public track.
    source    : eligible resolved outcomes exported from the live system.
    """
    missing = {k: source[k] for k in source if k not in published}
    extra = {k: published[k] for k in published if k not in source}
    flipped = {k: {"published": published[k], "source": source[k]}
               for k in published if k in source and published[k] != source[k]}
    matched = sum(1 for k in published if k in source and published[k] == source[k])
    ok = not (missing or flipped or extra)
    return Reconciliation(ok=ok, matched=matched, missing=missing, flipped=flipped, extra=extra)


def published_resolved(track_path) -> dict:
    """Resolved ``{src: outcome}`` parsed from a published track (hash-chained JSONL).

    Keys on the stable source id ``src``; a resolve event without ``src`` falls back
    to its prediction's ``src``, then to the prediction id — so any track reconciles.
    """
    events = AuditChain(track_path).read()
    pred_src = {e["event_data"]["id"]: e["event_data"].get("src", e["event_data"]["id"])
                for e in events if e["event_type"] == "predict"}
    resolved = {}
    for e in events:
        if e["event_type"] != "resolve":
            continue
        d = e["event_data"]
        key = d.get("src") or pred_src.get(d["id"], d["id"])
        resolved[str(key)] = int(d["outcome"])
    return resolved


def load_source(source_path) -> dict:
    """Load the operator's source export into ``{src: outcome}``.

    Accepts a JSON object ``{src: outcome}``, a JSON list of ``{"src","outcome"}``
    records, or JSONL (one such record per line). Only ELIGIBLE, RESOLVED items
    belong in the export — the operator's read-only query owns that filter.
    """
    text = Path(source_path).read_text(encoding="utf-8").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    if isinstance(data, dict):
        return {str(k): int(v) for k, v in data.items()}
    return {str(r["src"]): int(r["outcome"]) for r in data}
