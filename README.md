# MarketPulse

A token trading lab is available at `/paper`: one token equals $1 of simulated buying power. It includes isolated practice accounts, historical replay, live-quote plumbing, auditable orders, performance analytics and the fixed seven-day agent challenge. See [PAPER_TRADING.md](PAPER_TRADING.md) for execution assumptions, the empirical rehearsal, live-data prerequisites and the current cash-until-validated agent policy.

Now includes real US-stock and cryptocurrency archive ingestion, durable backfill jobs, a 60/20/20 chronological predictability lab, and an interactive options learning page. See [HISTORY.md](HISTORY.md) for the current data scope, commands, methodology and network limitations. The default page is the evidence lab; the earlier pattern terminal remains at `/terminal`.

Runnable Python 3.11+ quantitative research application with four pipelines: public-data ingestion → DuckDB → causal features and historical matrix → cosine/DTW analog inference → FastAPI REST/WebSocket dashboard.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
python cli.py bootstrap --market both
python cli.py research
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 (evidence lab), /guide/options (learning calculator), /terminal (original pattern terminal), or /docs (OpenAPI). Real-data mode is the default. Setting `MP_DEMO=true` seeds 2,400 deterministic **synthetic**, continuous one-minute SPY bars. These are not actual exchange data; the fixed historical timestamp and source badge remain visible. Demo sends a snapshot followed by WebSocket heartbeats, not fake live prices.

```bash
pytest -q
python cli.py ingest SPY --provider yahoo --start 2025-01-01T00:00:00+00:00 --end 2025-02-01T00:00:00+00:00 --interval 1d
python cli.py sec 320193
python cli.py index SPY --source synthetic --output patterns.npz
```

Daily data cannot support intraday inference: select enough minute data for +5m/+1h. Yahoo intraday retention is limited; Alpha Vantage intraday may require paid entitlement. Neither provider promises free tick history. Provider errors and rate limits are surfaced; requests have bounded retries. External connectors require destination network access and were tested using mocked responses, not live credentials.

## Four pipelines

1. `core/models.py` enforces aware UTC timestamps, finite values, valid candles and symbols. `core/db.py` stores idempotent provider-specific candles, deduplicated raw trades, event metadata, and predictions. Parameterized SQL and a lock protect the embedded connection. Aggregation uses OHLCV semantics; partially filled buckets may appear and are not automatically indexed.
2. `features/indicators.py` provides RSI, normalized MACD, Bollinger position, realized volatility, moving-average convergence, candle shapes and volume features. VPVR assigns volume at typical price and is an approximation. Signed candle volume is explicitly a proxy, **not measured order flow**. Fixed causal scaling avoids global future-data normalization. Patterns use non-overlapping windows and a scikit-learn cosine index; `index` exports compressed versioned matrices.
3. `engine/patterns.py` ranks historical analogs using cosine plus bounded DTW. Each horizon independently excludes all outcome labels at or after the query window start. Exact timestamp matching prevents substituting tomorrow's open for a missing +5m target. +1d means 24 elapsed hours, not next trading session. Short history yields unavailable predictions. Current implementation accepts configurable window lengths; interval and window must be selected explicitly. `ingestion/live.py` provides Alpaca IEX trade WebSockets with authentication, reconnect backoff, idempotent trade storage, and completed-minute aggregation. The final open minute remains pending until a later trade. Late trades are counted and dropped from aggregation. It does not fill missing minutes or model exchange corrections. IEX is partial-market coverage, not consolidated US equity volume.
4. `api/main.py` serves REST candles, import, signals, VPVR, chronological evaluation, health, and bounded WebSocket fanout. `/ws/signals/SPY` sends actual completed-bar updates when Alpaca is configured. `engine/ml.py` optionally trains a separate XGBoost benchmark with a chronological holdout and horizon purge; install `.[ml]` to use it. Neural networks were not added without a training dataset.

## Real data

Set `MP_DEMO=false`, configure Alpaca key/secret, and restart to stream SPY on the IEX feed. Historical provider and Alpaca data remain separate because coverage differs. Warm up with sufficient Alpaca bars (POST /api/bars with source `alpaca_iex`) or wait for accumulated history; no signals are fabricated during warm-up. Other symbols can be ingested and analyzed historically; the built-in live subscription currently tracks SPY only. Never commit `.env`.

SEC requires `MP_SEC_USER_AGENT` containing identifying contact information. The SEC connector ingests recent filing metadata at acceptance time, not filing period end. It does not yet download filing bodies or paginate old submission archives. `FREDIngestor` accepts a FRED key and stores initial vintage observations with day-level publication availability; day-level data must not be joined to intraday features without a conservative release-time policy. Sentiment and full order book ingestion are extension points, not implemented datasets. SEC/macro events are persisted separately and are not silently used as trained price features.

## Statistical interpretation

Directional outputs are similarity-weighted historical outcome frequencies, not calibrated probabilities. Approximate Wilson intervals use effective sample count; autocorrelation and analog selection can invalidate nominal coverage. Similarity is not accuracy. Alerts require at least ten analogs, frequency ≥ configured threshold, and an interval excluding 50%. Historical accuracy remains null in signals until separately evaluated; `/api/backtest/{symbol}` provides horizon-specific accuracy, Brier score, sample count and an always-up baseline using causal chronological replay. Results are not a trading profitability claim: no fees, slippage or execution model is included. Continuous synthetic data only validates software behavior.

## API

- `GET /health`
- `GET /api/bars/{symbol}?interval=1m&source=synthetic&limit=400`
- `POST /api/bars` with `{ "bars": [OHLCV objects] }`
- `GET /api/signals/{symbol}?source=synthetic`
- `GET /api/backtest/{symbol}?source=synthetic`
- `GET /api/profile/{symbol}?source=synthetic`
- `WS /ws/signals/{symbol}?source=synthetic`

## Deployment boundaries

This is a local, single-process research baseline. Bind to loopback; mutation routes have no authentication. Do not expose publicly before adding authentication, authorization, rate limiting, request-size limits and TLS. Use one uvicorn worker with DuckDB. The store Protocol is the extension boundary for a PostgreSQL/Timescale adapter; that adapter is not implemented. Asyncio and bounded subscriber queues provide local processing; Redis/Celery are not necessary for this baseline. Production work includes incremental index updates (current inference rebuilds an in-memory index), durable job orchestration, exchange calendars and gap policy, corporate-action handling and survivorship controls, true order-flow feeds, trained volatility clustering, point-in-time event joins, model calibration, monitored drift, and walk-forward profitability evaluation. The original pattern-terminal API queries at most 20,000 bars. The historical research path reads the full stored daily series without that cap; large intraday research still needs a partitioned design.

The supplied specification ended at `SECData`; this implementation follows the complete four-pipeline architecture and documents features that remain extension work.
