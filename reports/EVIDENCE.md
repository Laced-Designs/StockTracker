# Historical predictability findings

The current analog model has **not established a predictive edge** after the experiment's statistical controls. This does not establish that every market model is unpredictable.

641,156 actual observations are stored: 619,017 stock candles across 505 symbols and 22,139 cryptocurrency daily prices across six assets. Twenty-three invalid stock rows were quarantined. The research analyzed 503 instruments: 498 stocks and five crypto assets. Eight series were skipped because their histories were too short, including SOL with only seven usable prices.

Stock archive coverage is February 2013–February 2018; it is a static, survivorship-biased universe. The five analyzable crypto archives end in May 2026. BTC begins in July 2010, ETH in August 2015, LTC in April 2013, DOGE in January 2014 and ADA in December 2017. These snapshots do not describe current prices.

The experiment freezes 60% for training, uses 20% for window selection, then evaluates the remaining 20% with a query-window embargo. It compares 15/30/60-observation patterns and 1/5/20-session horizons. A common training-prior baseline is used across pattern-window choices. Probability outputs are not calibrated. Date-clustered block tests and multiple-test corrections are approximate, and do not establish profitability.

| Market | Horizon (sessions/days) | Test rows | Directional accuracy | Always-up accuracy | Brier improvement vs prior | Adjusted q | Evidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| US stocks | 1 | 93,284 | 50.7% | 53.0% | -0.01996 | 1.000 | not established |
| US stocks | 5 | 18,548 | 50.3% | 55.2% | -0.02946 | 1.000 | not established |
| US stocks | 20 | 4,367 | 53.6% | 62.3% | -0.02765 | 1.000 | not established |
| crypto | 1 | 1,085 | 50.2% | 47.6% | -0.01758 | 1.000 | not established |
| crypto | 5 | 823 | 51.4% | 49.5% | -0.01453 | 1.000 | not established |
| crypto | 20 | 204 | 56.4% | 43.1% | +0.00252 | 1.000 | not established |

Positive Brier improvement means lower probability error than the training-prior baseline; a negative value means worse error. Cross-stock test rows are correlated and are not treated as independent market histories in the evidence test. The small positive crypto 20-day improvement did not establish an edge. Per-instrument results, regime breakdowns, validation scores, partition dates and input fingerprints are in `predictability.json`.

4,249 durable jobs were planned for 523 stock/ETF symbols and monthly BTC/ETH/SOL spot archives. 4,247 remain pending and two are blocked by the enforced network policy. No hosted continuous process is claimed. Enable destination access for `query1.finance.yahoo.com` and `data.binance.vision` through supported environment settings, then run the backfill command with `--retry-failed`. See `HISTORY.md` for the bounded runner and optional tracking loop.

Options analytics are educational European Black–Scholes scenarios, not historical options predictions. Open `/guide/options` to explore Greeks, IV and expiry P&L. Actual options-strategy research needs point-in-time chains, bid/ask quotes and contract specifications.
