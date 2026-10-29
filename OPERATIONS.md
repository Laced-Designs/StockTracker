# Operations, security and acceptance

## Service health

`GET /api/health` separates collector state, feed freshness, Redis connectivity, provider errors and exchange session. `ready` requires eligible fresh symbols and a running collector; it is not a promise that every symbol or prediction is available. The UI reconnects WebSockets with capped exponential backoff, refreshes REST state, and disables submission when health is not ready. Every fill is timestamped and quotes must be newer than submission. Each client queue is bounded; old ticker frames can drop instead of growing memory without bound. A heartbeat preserves the connection during idle periods.

Start one worker only. If the collector stops, diagnose the error before restarting. Do not inject synthetic quotes into live accounts. A deployment needs an external supervisor and uptime alerts; this editor environment is not persistent hosting. No scheduled study has been re-enabled.

## Before shared or public deployment

- Add authenticated user ownership and recovery, API rate limiting, capability-key rotation/revocation, account quotas and security audit. The current account capability is a private bearer secret, not a complete identity platform. Account creation is unauthenticated; keep the app private.
- Use TLS, strict allowed origins/hosts, a restrictive CSP compatible with the bundled chart and an authenticated reverse proxy. Do not expose PostgreSQL/Redis. Keep provider secrets in deployment bindings.
- Add schema-versioned migrations instead of relying on first-run `create_all`; test migration upgrades and backups/restores. The database schema is initial-version bootstrap only.
- Exercise PostgreSQL concurrent row locks and Redis loss/reconnect under deployment load. Local acceptance uses SQLite; do not equate it with a PostgreSQL load test.
- Add dedicated ingestion leadership/sequence recovery before horizontal scaling. Test process/network crashes around fills and expiry. Implement durable quote/expiry evidence and manual settlement review for outages.
- Obtain licensed market/news data, verify provider timestamps/entitlements, corporate actions, sessions and option contracts. Do not market model-generated premium/depth as actual option/Level 2 data.
- Train on real as-of history; evaluate untouched future windows, dependence-adjusted uncertainty, calibration and net costs before making predictive claims. Beta/Sharpe need aligned session histories, not per-tick annualization.

## Browser acceptance

1. Start the default demo. Check the simulation badge, chart/news overlays and synthetic depth label at desktop and mobile sizes.
2. Create a token account; submit a fractional market buy. Confirm pending reservation then a later quote fill. Inspect Positions and Activity.
3. Submit a low limit buy, cancel it and verify reserved cash releases. Reject an oversized buy or uncovered short option.
4. Open model Options and inspect calls/puts, whole-contract quantity, volatility provenance and Greeks. Enter a valid strike/expiry and submit a funded contract.
5. View Analytics for Brier baseline and non-causal feature contributions. View Learn for exposure/expiry limitations.
6. Disconnect the feed; verify the unavailable state, then reconnect. Import/export a private account only to a trusted local file. Export a bug report without credentials.

## Current implementation boundaries

No real brokerage execution; no verified listed option chains; no early assignment/physical delivery; no consolidated Level 2 feed; no live FinBERT default; no claims of validated edge. Position snapshots and activity are persisted; cache and live in-memory chart bootstrap are not a durable all-history store. Option post-mortems retain submission context but do not infer causal attribution. Shared bug-triage backend and collaborative tasks are future features.

## Verified locally

19 Python tests pass on SQLite; TypeScript and the production Vite build pass. Chromium acceptance covers account creation, a subsequent-quote equity fill, a model-option fill, limit cancellation, positions/activity, analytics, education and a 390px mobile viewport with no horizontal document overflow or browser exceptions. `npm audit` reports zero known vulnerabilities at build time. These checks do not establish provider availability, PostgreSQL load performance or security readiness for a public service.

Run `python tests/browser_smoke.py` against a locally running demo app for the browser flow (requires installed Chromium at `/usr/bin/chromium`). It creates disposable demo accounts and saves screenshots to `/tmp`. Do not run it against a live-data/shared deployment.

The redesigned personalized navigation is verified with `tests/browser_navigation.py`. Preference storage is browser-local and does not include account access keys. Goals do not modify funds or execution rules. No study automation has been enabled.
