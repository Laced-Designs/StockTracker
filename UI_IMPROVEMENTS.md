# Overview and task access

The app now opens at an overview dashboard. `/paper`, `/research`, `/tasks`, `/reports`, and `/bugs` are available from the main navigation. The pattern terminal remains at `/terminal`; options education remains at `/guide/options`.

The overview reads `/api/overview` every 30 seconds with a 12-second timeout and manual retry. Collector status reflects actual background-task state, separately from API availability and quote freshness. Disconnection labels the display stale; a running task alone does not imply healthy data. Balances carry their valuation time. Goal progress includes the initial 500 tokens; independent experiment allocations are never pooled.

The public leaderboard and activity timeline include only the original challenge and mapped study arms. Private user accounts and capability keys are excluded. No filled trades means “Not started”; missing fresh marks means “Unpriced.” Historical and hypothetical options results remain outside the forward leaderboard.

Tasks show checkpoint coverage, not successful trading or guaranteed continuous collection. Reports link to timestamped repository exports. Existing source limitations remain visible.

Bug drafts are stored locally in the user's browser and can be downloaded as JSON for review. They are not shared across devices or automatically filed as GitHub issues. Only a small status context is exported; credentials and private account state are not attached automatically. Users should review all entered text before sharing.

## Validation

41 tests pass, including private-account isolation and stopped-collector detection. All dashboard scripts pass Node syntax checks. Chromium checks exercised overview rendering, mobile overflow, bug draft persistence/clear, and browser console errors using an isolated temporary database.

## Remaining operational work

The workspace process is not durable hosting. Add deployment supervision, restart policy and external uptime monitoring before claiming continuous collection. Live provider access remains restricted; quoted option execution remains unimplemented. UI changes do not remove these blockers.
