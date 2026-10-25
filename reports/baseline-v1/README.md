# Token baseline v1 — reference experiment

**Historical replay, not live performance.** This run establishes a fixed descriptive reference for future candidate policies. Previously inspected archives are not an independent holdout.

Each independent scenario begins with **500 tokens = $500 simulated USD**. Four policies across eight instruments and 13 windows per instrument produced **416 simulations / 104 asset-windows**. Dates shared across instruments are correlated: each market group has 13 distinct endpoint dates.

US stocks: AAPL, MSFT and JPM, with archive data through February 7, 2018. Crypto: BTC, ETH, LTC, DOGE and ADA, with reference prices through May 23, 2026. Results are separated by market. The horizon is seven observed intervals: stock trading sessions or crypto calendar days. No result contributes to the separate forward seven-day agent challenge.

## Starting results

| Market | Policy | Asset-windows | Mean ending tokens | Mean net return | Worst net return | Maximum observed drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| US stocks | cash | 39 | 500.00 | +0.000% | +0.000% | 0.000% |
| US stocks | buy_hold_25 | 39 | 500.43 | +0.086% | -1.565% | 1.873% |
| US stocks | buy_hold_100 | 39 | 501.73 | +0.345% | -6.259% | 7.378% |
| US stocks | momentum_25 | 39 | 500.12 | +0.023% | -1.372% | 1.873% |
| crypto | cash | 65 | 500.00 | +0.000% | +0.000% | 0.000% |
| crypto | buy_hold_25 | 65 | 500.74 | +0.147% | -2.551% | 2.566% |
| crypto | buy_hold_100 | 65 | 502.95 | +0.589% | -10.202% | 10.202% |
| crypto | momentum_25 | 65 | 499.32 | -0.135% | -2.482% | 2.545% |

Momentum underperformed matched-entry-budget buy/hold by an average 0.063 percentage points in stocks and 0.283 percentage points in crypto. This is a descriptive comparison, not statistical proof of superiority or inferiority. A 25% entry cap does not equate realized exposure or risk. Cash is also a required benchmark.

## Fixed rules and costs

- Cash: retain the starting 500 tokens.
- Buy/hold 25%: buy with a 125-token budget, including fees; retain remaining cash.
- Buy/hold 100%: buy with a 500-token budget, including fees.
- Momentum 25%: positive five-observation momentum and 5-period mean above 20-period mean; entry budget at most 125 tokens. Exit on loss of signal or close-observed -5%/+10% move, or on the precommitted final exit.
- Every side pays 10 bps fees, 5 bps adverse slippage and half of a modeled 10 bps total spread.
- Decisions use observations through their own clock. Orders fill at the next observed price. The final exit is submitted at observation 6 for execution at observation 7.

Directional hit rate is a diagnostic: a next-observation fill cannot earn the price move from the decision to that fill. Evaluate executable, after-cost returns separately. Daily reference prices cannot reconstruct intraday stops or liquidity; stock dividends and corporate actions are not modeled.

## Files

- `summary.json`: experiment ID, fixed configuration, source coverage/fingerprints, aggregate and paired results, future evaluation contract.
- `runs.csv`: one row per independent simulation, suitable for analysis.
- `traces.json.gz`: complete decisions, information cutoff, fills, forecasts and equity curves.

Trace SHA-256: `4bab1c63db926d0afdfce02cd8b03a8a28c5eb0fbace294a8dd8e60a1ac4d52b`.

The app stores this summary in `paper_trials` and displays it at `/paper` through `/api/paper/rehearsal`. Reproduce with:

```bash
python cli.py --database data/history.duckdb paper-baseline --windows 13
```

## Future decision-making

Freeze each new candidate before collecting new outcomes. Preserve token accounting, assets, price eligibility, execution lag and costs. Compare net returns and drawdown against cash and matched-budget buy/hold on new observations. Collect at least 30 new non-overlapping date-windows as an initial diagnostic, with the eventual sample requirement adjusted for dependence and statistical power; a count of 30 alone proves nothing. Do not promote a strategy solely because it improved on these already examined archives. Live forward evaluation still requires approved feeds and a persistent process.
