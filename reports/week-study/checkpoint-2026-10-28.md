# Day 3 checkpoint — October 28, 2026

Observed at 2026-10-28T17:38:20.821655Z (10:38 a.m. Pacific). Focus: long-call/put time decay and volatility sensitivity. Actual checkpoint days 0–3 are recorded; no due calendar-day checkpoints are missing. This does not establish uninterrupted runtime or feed coverage.

The existing API was unreachable and no collector process was present. The standalone checkpoint completed before the single-process collector was restarted with study collection and live polling enabled, original challenge automation disabled. Restart health returned ok. Interruption onset and total downtime remain unknown; no catch-up observations or trades were generated.

No fresh eligible quotes, study arms or scoped orders were found. The original challenge retains 500.00000000 cash tokens, zero fees and no positions, awaiting live data, with its original 2026-11-01T18:15:32Z deadline. No target crossing is evidenced. Study end remains 2026-11-01T19:53:06.493933Z. Separate allocations are never pooled. Spot remains fully funded without borrowing and one token represents one simulated USD.

## Review of existing calibration, not new forward evidence

Reviewed the saved October 25 historical European option scenarios without recomputation. Each volatility-shock/right group contains 39 correlated scenarios. Existing mean modeled returns for calls at -10/0/+10 volatility percentage-point shocks are -15.25% / +3.02% / +28.25%; puts are -26.66% / -2.10% / +33.11%. These differences illustrate sensitivity to assumed volatility; they are not realized IV observations, forecast skill or this week's returns.

A saved AAPL call example entered February 1, 2018 with a hypothetical February 15 expiry. Its remaining life declines from 14 to 8 calendar days by the February 7 mark, retaining pre-expiry time value. Entry model theta is approximately -0.08468 USD per share per calendar day and vega approximately 0.12821 USD per share per one volatility percentage point. At the assumed 100-share multiplier, those are local sensitivities near -8.47 tokens/day and +12.82 tokens/volatility point for one contract, holding other inputs fixed. Realized P/L cannot be attributed to theta alone because underlying price, volatility, Greeks and modeled execution costs also change. The saved example's initial delta-notional/equity multiple is about 19.58x despite a fully funded premium; premium funding is not unleveraged exposure.

The hypothetical strikes/expiries are not verified as listed; starting volatility is trailing realized volatility, not observed IV. European pricing is not an American exercise model. The 234 scenarios remain calibration only and do not create new forward samples. No live option-chain connector or quoted-option execution exists, so forward option theta/IV and execution outcomes are unavailable. Whole contracts and fully paid premiums remain requirements. No uncovered options, borrowing or real-money orders occurred.

Coinbase remains excluded by enforced network policy and no provider secrets are configured. Existing network and runtime blockers are preserved. No unchanged tests were rerun to inflate activity. Results remain scheduled after the study window closes.
