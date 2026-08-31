# calibration-log

**A public, append-only, hash-chained track record of predictions — scored over time. Honesty you can't doctor.**

Anyone can *say* they call things well. This is the version you can't fake: every prediction is logged **before** the fact with a probability and a resolution date, sealed into a hash-linked chain, and committed to public git history. When it resolves, it's scored. Over time the **Brier score** and **calibration table** show — to anyone — how well-calibrated the forecaster actually is.

It's the externalized form of one discipline: *no belief without verification*, turned on your own judgment.

## Use it

```sh
pip install -e .

# log a prediction — probability in (0,1), with a resolution date
calibration-log predict "BTC above \$80k by Aug 1" --prob 0.35 --by 2026-08-01

# later, resolve it
calibration-log resolve p1 no

# see the running score any time
calibration-log score

# push the public record
calibration-log publish
```

Each `predict` / `resolve` appends to `predictions.jsonl` (hash-chained, tamper-evident), regenerates [`SCOREBOARD.md`](SCOREBOARD.md), and commits.

## Why it's trustworthy

- **Pre-registered** — predictions are logged *before* the outcome, with a probability and a deadline.
- **Tamper-evident** — `predictions.jsonl` is a SHA-256 hash chain; edit any past entry and the score reports the chain **BROKEN**.
- **Public** — it lives in git history, so timestamps can't be backdated without it showing.
- **Scored** — Brier score (lower is better; `0.25` = no skill, `0` = perfect) plus a calibration table (predicted vs. actual frequency).

## Govern it — `verify`

The score tells you *how* calibrated; `verify` tells you whether the record is
*honest to look at*. It's a runnable gate — exit 0 iff it passes — that anyone can
re-run on the public log:

```sh
calibration-log verify                     # the main log
calibration-log verify --track yggdrasil   # a named track
```

It checks three things and reports each:

- **chain integrity** — the SHA-256 hash chain is intact (a broken chain fails hard).
- **auto-suspect** — a hit-rate over 65%, or an implausibly low Brier, is *flagged* rather than bragged about: per the discipline this repo externalizes, a too-good record is *a bug to disprove* (look-ahead? leakage?), not a win to claim.
- **staleness** — predictions past their resolution date but still unresolved (how a feed quietly stops being current).

`--strict` makes auto-suspect / staleness fail the gate too; `--json` emits a machine-readable verdict. A broken chain always fails.

## The scoreboard

See [`SCOREBOARD.md`](SCOREBOARD.md) — auto-generated from the log, empty until the first prediction resolves. A populated board looks like:

```
**Brier score: 0.18** — lower is better (0.25 = no skill, 0.0 = perfect)

## Calibration
| range | avg predicted | actual freq | n |
|---|---|---|---|
| 0.6-0.8 | 0.70 | 0.67 | 6 |
| 0.2-0.4 | 0.30 | 0.25 | 4 |
```

## Tracks

Beyond personal predictions, the log hosts **dedicated tracks** — e.g. an automated system publishing its own record. See [`tracks/YGGDRASIL.md`](tracks/YGGDRASIL.md): the real, scored track record of the **Yggdrasil** paper-trading system — published honest-negative (Brier ≈ no-skill), losses and all, with Nevada court-order categories excluded. That's the point: a record you can't curate.

The Yggdrasil track is also **reconciled against its live source**: a read-only check (on the operator's side, where the system's database lives) proves every eligible resolved trade is published, with the *same* outcome the system recorded — so the public record can't be quietly cherry-picked or doctored, only completed. **This is a runnable check, not a promise** — see [Reconciliation](#reconciliation).

## Reconciliation

The claim above is mechanized, not asserted. The reconcile engine compares the published track against a read-only export of the live system's **eligible, resolved** outcomes — keyed by the stable source id `src` — and fails on any of:

- **MISSING** — the source recorded a resolved item the track omits (a hidden loss → cherry-picking)
- **FLIPPED** — a published outcome differs from what the source recorded (doctoring)
- **EXTRA** — the track publishes an outcome the source never recorded (fabrication)

```sh
# operator-side: export the live system's eligible resolved outcomes (read-only) as
# {src: outcome}, a list of {src, outcome}, or JSONL — then reconcile:
calibration-log reconcile --track yggdrasil --source source-export.json
# exit 0 = every eligible resolved item is published with the same outcome
# exit 1 = divergence (prints the MISSING / FLIPPED / EXTRA items)
```

The logic lives in [`calibration_log/reconcile.py`](calibration_log/reconcile.py) and is covered by [`tests/test_reconcile.py`](tests/test_reconcile.py). The source export is produced on the operator's side (the live database is operator-only), so this repo carries the *check*, not the system's schema.

## Feed it as a side effect — `hook`

This log was correct and empty for months, and it was not alone: a survey of the
surrounding repositories found four verification mechanisms built well and then never
fed. The cause is structural rather than personal. Feeding each one is a *separate
act* — stop, change directory, run a second tool in a second repository. That cost is
small and it is paid every single time, which is why every counter stayed at zero.

So registration moves onto something already done. Every unit of work ends in a commit,
and the message is written anyway. One more line in it:

```
Predict: 0.70 2026-12-31 the wired edge count is still exactly 17
```

```
calibration-log hook install --repo . --track <name>
calibration-log hook status  --repo .
calibration-log hook uninstall --repo .
```

`post-commit`, deliberately, not `commit-msg`. A hook that can reject a commit gets
bypassed with `--no-verify` and then deleted, and an unfed mechanism is the exact
failure this exists to fix. It cannot fail or delay a commit — every path in it ends in
`exit 0` — and it refuses to overwrite a `post-commit` hook it did not write.

Registration is keyed on the *content* of the prediction, not the commit, so a
`git commit --amend` re-presents the same claim and the second registration is refused
rather than duplicated.

A commit whose message carries a `VERIFIED` block but no `Predict:` line is **noted on
stderr and never rejected**. Criterion 4 of the Standard is *Calibrated*, and the honest
state of most work is that it makes no predictive claim — N/A, not a failure. Naming the
gap at the moment doneness is claimed is the deliverable; enforcing a quota would only
manufacture filler predictions and a Brier score that means nothing.

Trailers are anchored at column 0, and that is load-bearing. The first real commit this
shipped on registered a prediction whose claim was the literal text `<claim>` — the
parser had matched the indented *example* in the message's own prose. Git trailers live
at column 0 and every way of quoting one puts something in front of it, so the anchor
separates them exactly.

**The remaining cost is one install per repository**, and that is an honest one rather
than zero. A global `core.hooksPath` would make it zero across every repo at once, at
the price of a machine-wide setting that clobbers any other global hook — a trade worth
making deliberately, not by default.

## Retract without deleting — `void`

```
calibration-log void p1 --reason "parser artifact, never a real claim"
```

An append-only chain cannot be rewritten, which is the property that makes it worth
trusting. But it still needs a way to say *this entry was never a claim* — otherwise a
parser bug or a duplicate sits in the record forever, unresolvable except by inventing
an outcome for it. `void` appends a retraction with a reason; the original entry stays
in the chain, verifiable, and the scoreboard lists voided entries rather than hiding
them. A retraction is as permanent and as public as the claim was.

The abuse this obviously invites is voiding the predictions you lost, so the rule is
narrow and absolute: **a resolved prediction can never be voided.** A loss is by
definition resolved, so there is no path from a bad outcome to a clean record.

## Tests

```sh
pip install -e ".[dev]"
pytest
```

Runtime dependency: [`verity-core`](https://github.com/StellarRequiem/verity-core) — the hash-chained audit primitive is imported from the spine, not re-vendored, so `pip install -e .` pulls it. Otherwise standard library.

## VERIFIED

- **Tested** — `pytest` green: 31 tests (12 cover reconcile: the MISSING / FLIPPED / EXTRA vectors, the `src`-keyed track parser, all three source formats, and an end-to-end hidden-loss catch). CI runs the suite on Python 3.11/3.12/3.13 and dogfoods the `verify` gate.
- **Results** — live Yggdrasil track: 23 predictions · 22 resolved · Brier ≈ no-skill, losses included (an honest-negative record).
- **Live-proof** — `reconcile` run against the real `tracks/yggdrasil.jsonl`: an honest export of all 22 resolved items → `VERIFIED ✓` (exit 0); a doctored export (one flipped + one hidden loss) → `GATE FAILED` (exit 1), naming the MISSING and FLIPPED items.
- **Gaps** — the source export is operator-side (the live DB is operator-only), so CI exercises the reconcile engine on fixtures; the end-to-end reconcile against the live database is run by the operator.

## License

Apache-2.0. Built by [@StellarRequiem](https://github.com/StellarRequiem).
