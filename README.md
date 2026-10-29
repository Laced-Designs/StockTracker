# StockTracker

A fresh full-stack market research workspace with a React/TypeScript dashboard, news overlays, transparent predictive baseline and a virtual equity/options brokerage. Python 3.11+; Node 22+. **No real-money order integration. One $TRADE token represents one simulated USD and has no redemption value.**

## Quick start — entirely offline data

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
cd ui
npm ci
npm run build
cd ..
uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Open http://127.0.0.1:8000. The default `ST_MODE=demo` generates deterministic historical minute candles and synthetic classroom news; a seeded simulation updates quotes every five seconds. Charts, sentiment, depth and forecasts are visibly labeled. Start an account with configurable tokens, submit a trade, and wait for the **next** quote to fill. The current minute has zero volume on quote-only updates rather than an invented traded volume.

The browser stores account capabilities in **sessionStorage**. Export your private account file to reconnect after the browser session ends; import it in the account dialog. Anyone holding that key can access the simulated account. Never publish the file. Keys are hashed server-side. Private account responses are not cached. Different data modes cannot share an account.

For development, run FastAPI on port 8000 and `cd ui && npm run dev` in another terminal; Vite proxies API/WebSocket traffic. `/docs` documents the API.

## Modules

| Directory | Responsibility |
| --- | --- |
| `data_ingestion/` | Synthetic fixtures, read-only Alpaca history/quotes/news, sentiment, bounded fanout and optional Redis cache |
| `models/` | Causal indicators, chronological probability baseline, event studies, European Black–Scholes/Greeks/IV and offline research artifacts |
| `matching_engine/` | Decimal ledger, transactional reservations, market/limit/stop, whole option contracts, covered calls/cash-secured puts, expiry, exchange sessions |
| `api/` | FastAPI REST, capability authorization, persistence, WebSocket and production UI serving |
| `ui/` | React, Tailwind, custom responsive design, Lightweight Charts/event markers, news, orders, portfolio, model evidence and education |
| `tests/` | Accounting, next-quote execution, idempotency, stale data, holidays, options, causal feature and API checks |

## Live data and PostgreSQL / Redis

Set `ST_MODE=live`, configure read-only `ST_ALPACA_KEY`/`ST_ALPACA_SECRET`, and permit `data.alpaca.markets`. No provider credentials are included. Alpaca IEX quotes are **not** consolidated NBBO or Level 2 depth. Data entitlements and delay depend on the provider account. Historical bootstrap currently fetches up to 1,000 minute bars per configured symbol, not an all-history archive. Live news uses a transparent lexicon sentiment baseline; `Sentiment(finbert=True)` is an optional NLP adapter requiring the `nlp` extras and approved model-download access. FinBERT is not silently substituted for the baseline.

`ST_DATABASE_URL=postgresql+psycopg://...` uses PostgreSQL. Local SQLite is the offline fallback. SQLAlchemy account rows are locked on PostgreSQL; SQLite uses serialized write transactions. News, completed minute observations and account/ledger state are persisted. Redis caches recent quotes with a 30-second TTL and publishes ticker updates; Redis loss is labeled and the single-process publisher continues locally.

The app uses **one worker/publisher** per database: `--workers 1`. Redis is a cache/pubsub adapter, not a distributed execution coordinator. Do not scale app workers until ingestion leadership and ordered execution are implemented.

A deployment template is included:

```bash
# Put a strong POSTGRES_PASSWORD in .env; never commit it.
docker compose up --build -d
```

It binds the app to loopback, keeps database/cache private and adds restart policies. PostgreSQL/Redis Docker deployment is supplied for user deployment, not claimed as verified in this workspace. Put TLS, authentication, request throttling, monitoring and backups in front of any shared/public service. This is a tested implementation foundation, **not a certification of production readiness**. See [OPERATIONS.md](OPERATIONS.md).

## Execution and risk model

- Equities: fractional long positions; market, limit and stop orders; no borrowing or naked short equities. NYSE calendar gates live regular-session execution, including holidays and shortened sessions. Demo deliberately runs independently of exchange hours. Missing or stale quotes reject new orders and pause pending execution.
- Buys reserve cash including estimated fees/slippage; a market gap beyond the funded budget rejects the order. Limits never fill worse than their limit. Stops are triggered orders, not guaranteed execution prices. Reservations prevent reuse of the same shares or funds. Client IDs provide idempotency and reject changed payloads.
- Options: hypothetical **European cash-settled** calls/puts, 100-share multiplier, whole contracts only. Long premiums are fully funded. Short calls require 100 unreserved shares/contract; short puts reserve strike × 100. No naked short options. Collateral stays locked until a close/settlement. Options may create economic leverage despite full premium funding.
- Option marks use realized-volatility proxy inputs, 3% modeled premium spread per side and $0.65 per-contract per-side fees plus configured bps. These are **not listed contracts, real option bid/ask or observed IV**. The pricing endpoint can solve IV when the caller supplies a premium; this is a numerical calculation, not a provider chain.
- Expiry cash-settles intrinsic value, including worthless OTM expiry. A missing expiry-time price leaves settlement unverified and collateral locked. A covered call may liquidate its locked shares to fund cash settlement. Real US equity options commonly use American exercise and physical delivery; early exercise, assignment, dividends and splits are not modeled.
- Live quote gaps are not backfilled as trades. Restarts restore accounts but do not fabricate missed prices or expiry settlement. Long-term historical replays, full option chains and manual settlement review are future extensions.
- Fees/slippage default to 1/2 bps; configurable. Portfolio net equity deducts modeled liquidation fees; missing fresh marks remain unavailable. The short trial does not support reliable annualized Sharpe/beta, which are intentionally unavailable rather than invented.

## Prediction and explainability

The working hybrid is a fixed 50/50 ensemble of gradient boosting and regularized logistic regression using momentum, RSI, MACD, Bollinger position, realized volatility and news sentiment. It uses chronological 70/30 train/holdout, an embargo equal to the outcome horizon, train-only standardization and no future news. Recent feature/outcome windows must be continuous minute observations; gaps reduce eligibility. The dashboard reports holdout Brier score alongside a frozen train-prior baseline. Default horizon is five observed minute bars. Event studies evaluate +1/+5/+30 continuous minute returns/absolute moves/volume ratios using event **availability**, not only publication time. Insufficient samples have no correlation statistic.

Exact single-reference Shapley values explain the hybrid probability by enumerating all 64 coalitions of six features, replacing missing inputs with training means. Values sum to the difference from the reference probability; they are not causal driver percentages or population-background SHAP. Gradient-boosted mean and 5%/95% quantile regressors produce price targets and ranges; these are not forward-calibrated confidence intervals. LSTM/TFT, FinBERT training, daily-horizon models and calibrated distributions are extensions, not silently claimed features. Synthetic results and overlapping event windows establish no real predictive edge.

## Validation and offline artifacts

```bash
pytest -q
npm run build --prefix ui
python -m models.research
```

The last command writes a clearly labeled synthetic calibration report under `artifacts/`, never funding or advancing paper accounts. Browser acceptance steps and deployment limitations are in [OPERATIONS.md](OPERATIONS.md). No previous study data, scheduled trading tasks or old implementation has been reused or resumed.
