# Seven-day token rehearsal

These are **historical simulations**, separate from the forward live challenge. One token represents $1 USD of simulated buying power. Each run begins with 500 tokens.

The study covers 130 seven-day asset-windows across BTC, ETH, LTC, DOGE and ADA over the last roughly 180 days available in the May 2026 snapshots. Seven policy/cost configurations produced 910 runs; overlapping assets and shared dates mean these are not 910 independent market histories.

| Policy | Fee bps / side | Windows | Mean return | Worst return | Mean fees (tokens) | Ended at 1,000 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | 10 | 130 | +0.000% | +0.000% | 0.000 | 0.0% |
| buy_hold | 0 | 130 | -1.542% | -25.976% | 0.000 | 0.0% |
| buy_hold | 10 | 130 | -1.738% | -26.124% | 0.991 | 0.0% |
| buy_hold | 25 | 130 | -2.033% | -26.345% | 2.475 | 0.0% |
| momentum | 0 | 130 | -0.136% | -3.209% | 0.000 | 0.0% |
| momentum | 10 | 130 | -0.166% | -3.302% | 0.147 | 0.0% |
| momentum | 25 | 130 | -0.210% | -3.442% | 0.368 | 0.0% |

Cash preserved 500 tokens. The fixed momentum rule did not demonstrate a profitable edge in this rehearsal. Buy/hold uses 100% allocation; momentum entries are capped at 125 tokens, so the risk exposures differ. None of these results guarantees a future outcome.

Signals use only past observed daily prices, and queued orders fill on the next observation with modeled spread, slippage and fees. See `PAPER_TRADING.md` for exact assumptions, limitations and the fixed November 1 challenge deadline.

The full traces, forecasts, fills and equity curves are in `paper-rehearsal.json.gz`. Expand with Python's gzip module or `gunzip -k reports/paper-rehearsal.json.gz`. Re-run with `python cli.py paper-rehearsal`. The API integration exercise is recorded separately in `paper-smoke-test.json`; its two historical fills ended at 499.46509725 tokens, including 0.09946466 tokens of fees.
