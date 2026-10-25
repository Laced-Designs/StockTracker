# Seven-day study: collection artifacts

Protocol: [SEVEN_DAY_STUDY.md](../../SEVEN_DAY_STUDY.md). Study window: October 25, 2026 at 11:53 a.m. Pacific through November 1 at 11:53 a.m. Pacific. This is a new comparative study; the original 500-token challenge retains its earlier deadline.

- `status.json`: timestamped checkpoint export. Its presence does not prove continuous hosting or current quote coverage. Review observation timestamps, missing days and lane statuses.
- `options-model-summary.json`: historical theoretical calibration, not live or quoted-option performance.
- `options-model-runs.csv`: 234 historical long-call/long-put and volatility-sensitivity scenarios, including whole-contract funding and model equity.
- `options-model-traces.json.gz`: daily underlying observations, theoretical prices, days remaining, model volatility, Greeks and model delta-notional exposure. Strikes, expiries and spreads are hypothetical; these were not verified as listed contracts or actual quotes.

The initial calibration does not count as seven days of forward observations. Actual quoted options remain blocked because there is no option-chain connector or quoted-options execution implementation. Forward spot arms only fund and submit orders when fresh approved quotes arrive. A checkpoint invokes the eligible spot manager and records any orders in the ledger. A readiness check or queued order is not a fill; no existing archived price can fill a live arm.

Final reporting must separate actual forward spot fills, any genuine quoted-option observations, historical baseline results, theoretical option scenarios and blocked/unexecuted work. Read-only repo snapshots cannot establish current performance without an authoritative ledger and fresh data. Missing final prices remain unverified.
