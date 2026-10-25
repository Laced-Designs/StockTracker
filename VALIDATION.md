39 tests passed on Python 3.12.14.

Coverage includes the original schemas, DuckDB persistence, aggregation, provider separation, future-data invariance, minute finalization, tick deduplication, API and WebSocket behavior, plus archive quarantine, bulk idempotence, resumable planning, network-policy preflight, job lifecycle, unfinished-candle exclusion, crypto checksums and microsecond timestamps, frozen research partitions, a common training baseline, vectorized feature equivalence, evaluation density, date clustering, multiple-test correction, put-call parity, numerical delta and IV roundtrip.

Public stock and Coin Metrics archives were downloaded and imported. A full real-data experiment analyzed 503 instruments. Yahoo/Binance destinations are not permitted by the enforced runtime network policy; their queued jobs were marked blocked without attempting outbound requests. Browser rendering and real options-chain ingestion were not exercised. A Starlette test-transport deprecation warning remains; it does not fail tests.

The added paper-trading checks cover Decimal balance conservation, idempotent orders, pending reservations, no overdrafts/shorting, account-key isolation, shared replay quotes, stale/future-price rejection, next-observation fills, partial exits, deadline/DST preservation, ending-equity scoring rather than peaks, pre-deadline valuation cutoffs, isolated rejected orders, causal rehearsal decisions and Coinbase response parsing. An actual-data API buy/sell rehearsal completed. All dashboard JavaScript passed Node syntax checks, including a repaired line-break error in the existing options guide.

Cross-market baseline tests additionally verify that identical signals and matched entry budgets produce identical execution, stock source identity is preserved, decision information cutoffs precede fills, and summary comparisons stay separated by market.

Seven-day study checks cover calendar-week versus session timing, DST, whole-contract affordability, model volatility sensitivity and pre-expiry time value, causal funding inputs, missing-day visibility, next-quote spot fills and isolation from the original challenge.

The pre-weekend stock exit test verifies that planned liquidation waits for a subsequent real quote, closes funded positions, and does not reopen them after the cutoff.
