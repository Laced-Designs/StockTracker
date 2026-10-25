# Historical tracking and predictability research

The working database is `data/history.duckdb`. It contains real public archive observations; synthetic demo data is kept separate. The default page is now the evidence lab at `/`, with the original pattern terminal at `/terminal` and options learning at `/guide/options`.

## What “all history possible” means here

Collect the earliest accessible observations for each configured instrument and granularity, preserve the original source, and expose what is unavailable. It does not mean that all US ticks, delisted stocks, crypto venues, or options chains are freely available. Provider retention, licensing, delistings, coverage and entitlements limit what can be retrieved.

- The accessible stock bootstrap is a static 505-symbol archive spanning February 2013–February 2018. Its constituent list is survivorship biased. Invalid rows and conflicting duplicate keys are quarantined. This is not a current-market feed.
- Coin Metrics community archives provide daily USD prices for BTC, ETH, LTC, DOGE and ADA. SOL currently has too few usable archived prices to analyze. The exact retrieved coverage is recorded in the database. These price observations are stored separately from OHLCV; missing open, high, low or volume fields are never fabricated.
- Yahoo jobs request maximum daily history and retention-bounded 1-minute, 15-minute and hourly bars. The plan records requested ranges; a successful response does not certify completeness or corporate-action correctness. The current day's unfinished daily bar is excluded.
- Binance public monthly ZIP jobs cover BTC/USDT and ETH/USDT from 2017 and SOL/USDT from 2020, at daily and hourly granularity. Every retrieved ZIP is checked against its published SHA-256 checksum. Months are planned only after they have fully elapsed. Archive publication can lag. Missing files remain failed jobs, not invented candles.
- Exchange ticks, complete delisted-stock universes, point-in-time constituents and historical options chains require additional sources. SEC and macro connectors remain available from the original implementation.

Raw archive downloads are retained by SHA-256 in `data/raw`; accepted/rejected counts, retrieval times, original URLs and source limitations are persisted in `provenance`. Check upstream attribution and data terms before redistribution.

## Commands

```bash
# Public snapshots; network access to raw.githubusercontent.com is required.
python cli.py --database data/history.duckdb bootstrap --market both

# Queue all imported stock symbols plus liquid ETFs, and the crypto monthly jobs.
python cli.py --database data/history.duckdb plan --all-known-stocks

# Run bounded batches; retrying errors must be explicit.
python cli.py --database data/history.duckdb harvest --provider yahoo --limit 20
python cli.py --database data/history.duckdb harvest --provider binance_archive --limit 20
python cli.py --database data/history.duckdb harvest --retry-failed --limit 20

# Coverage and full-history research. This path has no 20,000-bar truncation.
python cli.py --database data/history.duckdb coverage
python cli.py --database data/history.duckdb research --output reports/predictability.json

# Optional ongoing backfill runner: 0 cycles means run until stopped.
python cli.py --database data/history.duckdb track --cycles 0 --interval-seconds 3600 --budget 20
```

Use one process with DuckDB: stop the API before running another process that writes the same database. The tracker is provided as a runnable loop, not a hosted scheduler. This chat does not guarantee a continuously running process. All jobs and observations survive restarts; rerunning the same plan does not duplicate jobs or candles. New days create new refresh jobs. A provider denial is recorded and suppresses repeated calls to that provider within the current batch.

In this managed environment, GitHub public archives are reachable. Direct Yahoo/Binance hosts are not currently in the enforced network allowlist. The runner preserves pending/blocked/failed work. To use those providers here, configure destination access for `query1.finance.yahoo.com` and `data.binance.vision` through the environment's supported network settings; application code does not bypass the policy.

## How the experiment works

1. Run each instrument independently on observed daily prices. The research features are log returns, momentum, realized volatility, RSI, Bollinger position and normalized price paths. Both asset classes use price-only features, making the crypto reference-price analysis explicit.
2. Freeze the first 60% of observations as training, the next 20% as validation and the last 20% as test. All scaling, historical analog templates, training-label priors and volatility-regime thresholds come from training. Every training outcome ends before the training boundary.
3. Compare 15-, 30- and 60-observation windows on validation Brier improvement against the frozen training prior. Select one window per instrument and horizon. Keep the entire query window beyond the preceding partition boundary. Do not select models on test results.
4. Evaluate the selected window on later untouched test observations, using up to 252 non-overlapping outcome windows per split. Daily horizons are 1, 5 and 20 observed trading sessions for stocks and daily observations for crypto. Crypto queries and labels reject date gaps. Daily history cannot validate +5-minute or +1-hour predictions.
5. Report Brier score, probability-error improvement, directional accuracy, always-up accuracy, training-prior accuracy and 20-period momentum accuracy. Include low/medium/high training-defined volatility regime breakdowns. Record negative results.
6. Date-cluster the Brier improvements before statistical testing, so 500 correlated stocks do not count as 500 independent market histories. Group consecutive observed test dates into 20-date blocks, perform a one-sided block random-sign test, estimate a block bootstrap interval, and apply Benjamini–Hochberg correction across all reported instrument/horizon and market aggregate tests. Fewer than three blocks yields no significance claim. At least 100 distinct test dates and positive interval/lift are required for a provisional-edge label. “Not established” includes weak, negative and underpowered findings.

The block procedure is approximate, especially when dates are sampled or market regimes change. It is not a guarantee of independence or nominal error control. Multiple experiments or repeated scrutiny of held-out results require a new future holdout. Window selection, per-series source preference and data fingerprints are recorded. No profitability, calibration or tradability claim follows from this experiment. Static universe bias, price adjustments, publication times, missing bars, fees and execution remain material limitations.

## Options while building

Open `/guide/options` for an interactive European Black–Scholes scenario calculator. It computes fair value, delta, gamma, daily theta, vega and rho per percentage point; it can solve IV from a supplied premium and draw expiry P&L with an explicit contract multiplier.

The calculator is educational and uses hypothetical values unless you supply a premium. Risk-neutral exercise probability is a pricing quantity, not actual win probability. American exercise, discrete dividends, volatility smiles, bid/ask spreads and crypto contract conventions can make its values unsuitable for a real contract. Equity and crypto options need independent point-in-time chain data to test an options strategy. Spot data is not used to fabricate it.

## Added API routes

- `GET /api/history/coverage` — series freshness, observed date gaps and job state.
- `GET /api/history/prices/{symbol}?source=coinmetrics_reference` — actual daily prices.
- `GET /api/research/latest` — the latest persisted research report, including failures to establish an edge.
- `POST /api/options/scenario` — European option analytics from validated explicit inputs.

Observed calendar gaps are diagnostics, not an exchange-calendar completeness guarantee. API mutations still have no authentication and must remain local until secured.
