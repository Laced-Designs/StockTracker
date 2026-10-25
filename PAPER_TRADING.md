# Token trading and seven-day challenge

Open `/paper`. **1 token represents $1 USD of simulated buying power.** Tokens have no redemption value and no real-money order path exists. Historical replay and live paper trading use separate clocks and eligible data sources.

## Practice accounts

Create an account with 500 tokens. Replay supports the imported stock daily OHLCV archive and crypto daily reference-price series. Pick an instrument and optional UTC start date. Orders queue at the current simulation clock and fill only on the next observation. The account history endpoint exposes only prices through that clock, although the broader research archive remains available: this is educational replay, not a blinded experiment.

Live paper accounts consume fresh Coinbase BTC/USD or ETH/USD bid/ask snapshots, or the existing Alpaca IEX tracking stream for SPY. Coinbase prices use actual USD quote pairs; USDT is not silently treated as a guaranteed dollar. Alpaca trade-based paper quotes explicitly use a modeled spread because the existing connector provides trades, not the full quote book. The Coinbase ticker includes the last trade timestamp, so quiet or stale tickers can block fills conservatively.

Buy orders specify a token budget including fees. Sell orders specify units held. Fractional units, average cost, realized P&L, pending reservations and cancelation are supported. No short selling, margin, borrowing, extra challenge deposits, or actual options orders are supported. Options education remains at `/guide/options`.

Accounting uses Decimal values, eight decimal places for tokens and twelve for units. Submitted order IDs are idempotent; reusing one for a different order is rejected. Fill and cash/position changes commit together. Each account receives a random capability key; its hash is stored and account API access requires the key as a Bearer token. The browser retains its own key in tab-local session storage. Keep it to retain access; there is no account-recovery service. This is still a local application, not a complete hosted identity system.

## Execution and valuation assumptions

- Market orders require a later provider timestamp, not a quote already seen before submission.
- Live quotes must be from an internal approved connector and within 120 seconds of both provider time and observation time. Future timestamps beyond two seconds of clock skew are rejected. There is no public quote-injection API.
- Historical daily execution occurs at the next observed price with a modeled total spread of 10 bps. It does not reconstruct historical bid/ask, intraday stops, or precise publication availability.
- Default fees are 10 bps per fill and adverse slippage is 5 bps per side. They are explicit educational assumptions, not a broker's quoted fee schedule. Historical sensitivity tests also run 0 and 25 bps fees. Liquidity/volume impact, dividends, splits during a replay, funding, tax and settlement are not modeled.
- Equity uses cash plus net liquidation value at bid after modeled exit costs. An open position with no fresh quote produces an **unavailable** equity value; it is not marked at purchase price or an old archive close.
- Pending buys reserve token budgets; pending sells reserve units. Overspending and overselling are rejected.
- Account analytics report net P&L, fees, turnover, average-cost sell-fill win rate, equity curve and drawdown. A seven-day trial does not receive an annualized Sharpe estimate.

## Agent challenge

The request was recorded at **October 25, 2026, 10:15:32 a.m. America/Los_Angeles**. The fixed deadline is **November 1, 2026, 10:15:32 a.m. America/Los_Angeles**, or `2026-11-01T18:15:32Z`. This is 169 elapsed hours because the clocks fall back during the requested calendar week.

The dedicated `seven-day-agent` account is funded once with 500 simulated tokens and has a 1,000-token ending-equity target. It cannot be reset or topped up through the user API. Its clock/deadline is never silently extended for missing data or downtime. It remains `awaiting_live_data` until a runner is enabled and a verified live quote arrives. Expiry cancels pending orders. Final valuation uses only quotes observed at or before the deadline and still fresh at the deadline; missing final prices produce an unverified result. A temporary peak above 1,000 does not count as a successful ending balance.

The objective is aspirational, not a guaranteed 100% return. Our prior research did not establish predictive value, and the fixed momentum rehearsal also had negative average net returns. The initial agent policy is therefore **cash-until-validated-v1**. It logs its decision to retain cash; it does not invent a predictive edge or add leverage to force trades. A new active policy needs an explicit version and a new future holdout. Users can independently practice orders in their own accounts.

The challenge state and decision log are readable at `/api/paper/challenge`. The simulator contains no user-accessible order-placement route for the agent account and never returns its private capability key. Cash and fresh buy/hold benchmark marks are recorded separately when it activates.

## Live readiness and running

This workspace's enforced network policy currently does **not** allow `api.exchange.coinbase.com`. Alpaca also requires configured credentials and WebSocket destination access. Stale stock/crypto archives cannot substitute for these feeds.

After configuring the supported network settings and a persistent process, enable:

```dotenv
MP_PAPER_LIVE_POLL=true
MP_PAPER_AUTO_CHALLENGE=true
```

Then run one process:

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

The application polls Coinbase every 60 seconds and performs a challenge step every 60 seconds while its lifespan is running. The existing optional Alpaca stream also publishes to the paper quote bus. This is not a hosted daemon merely because source code exists; stopping the process stops tracking. Downtime is not backfilled with fictitious fills. Do not concurrently run another writer against the same DuckDB file.

## Historical optimization dataset

```bash
python cli.py --database data/history.duckdb paper-rehearsal --days 180
python cli.py --database data/history.duckdb paper-status
```

The rehearsal covers 130 seven-day asset-windows across five crypto assets, with seven policy/cost configurations each: **910 simulation runs**, not 910 independent market histories. Policies are fixed in code: cash, fully allocated buy/hold, and 5/20-day long-only momentum with entry budget capped at 125 tokens. Signals use only observed history; fills use the next daily observation. Momentum exits on a loss of signal, a close-observed -5%/+10% threshold, or a precommitted final-day liquidation. These are next-observation exits, not guaranteed intraday stop orders.

The summary is persisted in `paper_trials` and shown in the app via `/api/paper/rehearsal`. Full simulation traces, orders, forecasts and equity curves are saved in `reports/paper-rehearsal.json` (compressed in Git). This is retrospective optimization data; it does not validate a future trading policy. Exposure differences and correlated assets/time windows limit comparisons. All runs remain distinct from the live challenge score.

## API

- `POST /api/paper/accounts` — create a separately funded practice account and return its access key once.
- `GET /api/paper/accounts/{id}` — account, orders and analytics; Bearer key required.
- `POST /api/paper/accounts/{id}/orders` — reserve a budget/position and queue a simulated order; Bearer key required.
- `DELETE /api/paper/accounts/{id}/orders/{client_order_id}` — cancel a pending order.
- `POST /api/paper/accounts/{id}/advance` — advance a replay account to its next actual observation.
- `GET /api/paper/accounts/{id}/history` — audit events and past replay observations.
- `GET /api/paper/challenge` — read-only agent challenge, readiness, benchmarks and decisions.
- `GET /api/paper/rehearsal` — most recent historical experiment summary.

## Frozen cross-market starting baseline

Run `python cli.py --database data/history.duckdb paper-baseline --windows 13` for a fixed 500-token-per-scenario comparison across AAPL/MSFT/JPM and BTC/ETH/LTC/DOGE/ADA. It adds a 25%-budget buy/hold control, preserves 10-bps fees and next-observation execution, and exports decisions and per-run CSV data. Results are shown in the app as the latest experiment. See [reports/baseline-v1/README.md](reports/baseline-v1/README.md). This is a descriptive historical starting point, not new live profit or an independent future validation.

## Seven-day spot/options study

The new study adds actual-time checkpoints, isolated spot study arms and clearly separated theoretical options sensitivity cases. See [SEVEN_DAY_STUDY.md](SEVEN_DAY_STUDY.md). The original challenge deadline is unchanged.
