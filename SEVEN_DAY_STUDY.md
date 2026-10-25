# Seven-day spot and options study

This study is separate from the original 500-to-1,000-token challenge, whose November 1 10:15:32 a.m. Pacific deadline remains unchanged. The new study protocol is `paper/study_plan.json`. It starts October 25, 2026 at 11:53 a.m. Pacific and closes November 1 at 11:53 a.m. Pacific. The calendar week spans 169 elapsed hours because daylight saving time ends.

Each test arm uses its own **500 simulated tokens**, with 1 token representing $1 USD. Results are per isolated experiment; virtual allocations are not pooled into one enlarged challenge balance. User clarification: 1-to-1 means **fully funded spot trading without borrowing**, not a 1:1 reward/risk ratio.

## Experiment lanes

| Lane | Execution / data | Current state |
| --- | --- | --- |
| Forward spot | Cash, 25%/100% buy-and-hold, and experimental 25% momentum; BTC/USD, ETH/USD and SPY when fresh approved quotes arrive | Blocked by current feed access; no live study fills claimed |
| Forward quoted options | Long calls and puts, verified bid/ask, listed strike/expiry, multiplier and exercise style | Blocked: no option-chain connector or quoted-options execution implementation is configured |
| Historical option sensitivity | Hypothetical European calls/puts on AAPL/MSFT/JPM archival underlying prices | 234 theoretical scenarios run as calibration; not quoted options trades or forward results |

Spot accounts use no borrowing, short selling or margin, and reserve budgets before orders. Cash accounts are the reference. Buy-and-hold uses either 125 or 500 tokens including fees. Experimental momentum requires 20 distinct provider-quote observations after study inception, a 5/20-observation trend and positive five-observation momentum. Its close-observed loss/profit thresholds are -5%/+5%; these are not guaranteed stop executions. This quote-observation rule differs from the previous daily-price baseline and is **not validated**. New orders fill only on a later fresh quote. Each account retains the fixed study deadline; no after-deadline fills are accepted. A precommitted SPY exit is submitted on Friday October 30 at 3:55 p.m. New York time, before the normal session close, because the study ends Sunday. Crypto exits are submitted five minutes before the study end. Buys stop at those cutoffs. Closures still need a subsequent real quote; a missing quote produces an unfilled exit or unverified final mark, never a synthetic weekend fill.

The options sensitivity lane uses whole hypothetical contracts with a 100-share multiplier, fully paid premiums and explicit modeled costs. Fully paid premiums do **not** imply unleveraged option exposure: delta-notional/equity is recorded. Starting strikes and expirations are hypothetical and are not verified as listed. Starting volatility is trailing realized volatility, not observed historical IV. A 14-day hypothetical expiry is set at entry, then the position is marked to model within seven calendar days. This retains time value; it does not misuse expiry intrinsic value for a pre-expiry mark. Terminal volatility shocks are -10/0/+10 percentage points. European Black–Scholes, zero dividends, a 4% rate, 3% adverse premium adjustment per side and $0.65 per contract per side are assumptions, not actual observed markets. Actual US equity options are often American.

## Daily protocol

0. Freeze the plan, validate accounting, and run historical calibration.
1. Record feed availability and any valid forward observations.
2. Audit decision times, fill latency and prediction horizons.
3. Review option time decay and volatility sensitivity.
4. Review fees, spreads, slippage and matched-budget controls.
5. Audit stale quotes, rejected orders, cash and position conservation.
6. Check coverage and decision logs before final reporting.
7. Publish combined results, drawdown, costs, gaps and lessons.

Checkpoints record actual observation times and calendar days. Calling the program repeatedly today does not generate tomorrow's observations. Missing days remain missing. A readiness observation is not a fill. The checkpoint also invokes the spot manager when quotes are eligible; any queued orders and subsequent fills are recorded in the paper ledger. Histories and theoretical models never fill a live account.

The collection window starts on Sunday. US stock markets are closed then; crypto has a different trading calendar. Report wall-clock coverage and session coverage separately. Correlated arms and volatility shocks are sensitivity cases, not independent samples.

## Running

```bash
# Historical theoretical calibration, explicitly separate from real option quotes.
python cli.py --database data/history.duckdb paper-option-tests --windows 13

# Record one actual-time readiness/execution checkpoint and export its status.
python cli.py --database data/history.duckdb paper-study-step

# Persistent single-process app, subject to approved network and quote access.
MP_PAPER_STUDY_ENABLED=true MP_PAPER_LIVE_POLL=true uvicorn api.main:app --host 127.0.0.1 --port 8000
```

`/paper` shows the study alongside the existing experiments. `/api/paper/study` exposes its protocol, actual checkpoints, spot arm valuations and model calibration metadata. The study loop checks every 60 seconds while the application is running, uses the existing paper quote bus, and records at least one checkpoint per observed calendar day. It stops the study loop at the fixed end time. The web application itself remains an ordinary running service.

Coinbase access requires `api.exchange.coinbase.com`; optional Alpaca streaming requires credentials and appropriate WebSocket access. Neither an editor session nor a scheduled status review guarantees uninterrupted hosting. If the process stops, there are no invented catch-up trades. Run only one writer for the DuckDB file. When a live API holds the database, scheduled checks should read the API rather than start a second writer.

## Artifacts and final report

`reports/week-study/status.json` is a timestamped export, not a live feed. The authoritative checkpoint ledger is `paper_study_checks`; the arm mappings are `paper_study_arms`; fills and cash use the existing paper ledger. Hypothetical options summaries, CSV rows and compressed curves are in the same report directory.

The final report must separate: verified forward spot results, any genuine quoted-option results, historical underlying tests, theoretical option sensitivities and unexecuted/blocked work. Report entry/fill timing, net equity, costs, drawdown, exposure, sample counts and missing intervals. A seven-day study cannot establish a reliable trading edge. The original challenge is scored using its own earlier deadline, even if both reports are delivered together later.
