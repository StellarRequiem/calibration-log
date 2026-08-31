"""Predictions carried in commit-message trailers — the side-effect route in.

Four verification mechanisms were built in this ecosystem and none were fed. The
common cause is not laziness; it is that feeding each one is a *separate act*. To
register a prediction you stop, change directory, and run a second tool in a second
repository. That cost is small and it is paid every single time, which is why the
count stayed at zero.

So the registration moves to something already done for its own reasons. Every unit
of work under the Standard ends in a commit, and the commit message is written
anyway. One more line in it costs almost nothing:

    Predict: 0.70 2026-12-31 an eighth false-positive class turns up in the resolver

A ``post-commit`` hook reads that and appends to the chain. The prediction is made at
the only moment it can honestly be made — before the outcome is known — and it is made
*in the same keystrokes* as the work it is about.

Two design choices worth defending:

``post-commit``, never ``commit-msg``.
    A hook that can reject a commit is a hook that gets bypassed with ``--no-verify``
    and then removed. This one cannot fail a commit and cannot slow one down. If it
    breaks it prints to stderr and the work is unaffected. A mechanism in the way of
    the work does not survive contact with a deadline.

A VERIFIED block with no trailer is *reported*, not rejected.
    Criterion 4 of the Standard is Calibrated, and the honest state of most work is
    that it makes no predictive claim — N/A, not a failure. So the absence is surfaced
    at the moment the claim of doneness is made, and nothing more. Naming a gap is the
    deliverable; enforcing a quota would just produce filler predictions and a Brier
    score that means nothing.

This module is pure: it parses text and computes ids. All I/O lives in the CLI.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

#: `Predict: <prob> <YYYY-MM-DD> <claim>` — one line, git-trailer shaped.
#:
#: Anchored at column 0 with NO leading whitespace, and that is load-bearing. The first
#: real commit this shipped on registered a prediction whose claim was the literal text
#: `<claim>` — the parser had matched the indented *example* in the message's own prose.
#: It is the string-literal bug from the import resolver wearing a different hat: text
#: that looks like a directive but sits inside a quotation. Git's own trailers are at
#: column 0, and every convention for quoting one (indent, fence, blockquote) puts
#: something before it, so the anchor separates the two exactly.
RE_TRAILER = re.compile(
    r"^Predict:[ \t]*(?P<prob>\d*\.?\d+)[ \t]*(?P<pct>%?)[ \t]+"
    r"(?P<by>\d{4}-\d{2}-\d{2})\s+(?P<claim>\S.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
#: anything shaped like a Predict trailer, so a malformed one is reported not dropped
RE_LOOSE = re.compile(r"^Predict:[ \t]*(?P<rest>.*?)\s*$", re.IGNORECASE | re.MULTILINE)
#: the Standard's closing block, at the start of a line
RE_VERIFIED = re.compile(r"^\s*VERIFIED\b", re.MULTILINE)


@dataclass(frozen=True)
class Prediction:
    prob: float
    by: str
    claim: str
    src: str


@dataclass(frozen=True)
class Parsed:
    predictions: list[Prediction]
    errors: list[str]
    verified: bool

    @property
    def uncalibrated(self) -> bool:
        """A claim of doneness carrying no forward claim. Reported, never blocked."""
        return self.verified and not self.predictions


def source_id(prob: float, by: str, claim: str, label: str = "") -> str:
    """A stable id for one prediction, so registering it twice is a no-op.

    ``git commit --amend`` rewrites the SHA, and a hook can be re-run by hand, so
    keying on the commit is not enough. Keying on the *content* means an amend
    re-presents the same prediction and the second registration is correctly refused.
    """
    digest = hashlib.sha256(
        f"{prob:.4f}|{by}|{claim.strip()}".encode()).hexdigest()[:16]
    return f"{label}:{digest}" if label else digest


def parse(message: str, label: str = "") -> Parsed:
    """Read a commit message. Never raises — a hook that throws is a hook removed."""
    good: list[Prediction] = []
    errors: list[str] = []

    matched_lines = set()
    for m in RE_TRAILER.finditer(message):
        matched_lines.add(m.group(0).strip())
        prob = float(m.group("prob"))
        if m.group("pct"):
            prob /= 100.0
        claim = m.group("claim")
        if not 0.0 < prob < 1.0:
            errors.append(f"probability must be in (0,1), got {prob:g}: {claim[:50]}")
            continue
        try:
            date.fromisoformat(m.group("by"))
        except ValueError:
            errors.append(f"unparseable date {m.group('by')!r}: {claim[:50]}")
            continue
        good.append(Prediction(round(prob, 4), m.group("by"), claim,
                               source_id(prob, m.group("by"), claim, label)))

    # A trailer that looks intended but does not parse is an error, not silence.
    # Losing a prediction quietly is the one failure this mechanism must not have.
    for m in RE_LOOSE.finditer(message):
        if m.group(0).strip() not in matched_lines:
            rest = m.group("rest")
            if not any(rest in e for e in errors):
                errors.append(
                    f"malformed trailer, expected `Predict: <prob> <YYYY-MM-DD> <claim>`: {rest[:60]!r}")

    return Parsed(good, errors, bool(RE_VERIFIED.search(message)))
