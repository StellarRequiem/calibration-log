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
