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

The Yggdrasil track is also **reconciled against its live source**: a read-only check (on the operator's side, where the system's database lives) proves every eligible resolved trade is published, with the *same* outcome the system recorded — so the public record can't be quietly cherry-picked or doctored, only completed.

## Tests

```sh
pip install -e ".[dev]"
pytest
```

No dependencies — pure standard library.

## License

Apache-2.0. Built by [@StellarRequiem](https://github.com/StellarRequiem).
