# Bug and usability register

| ID | Issue | State | Evidence / next action |
| --- | --- | --- | --- |
| UI-001 | No central view of tasks, performance and blockers | Fixed | Overview, tasks and reports routes with shared navigation |
| UI-002 | API availability could be confused with collector health | Fixed in overview | Actual task status, independent feed freshness, disconnected/stale state; `/health` remains basic process liveness |
| UI-003 | Empty trading tests could look like successful zero-loss strategies | Fixed | Not started and Unpriced labels, fill counts, timestamps, separate historical results |
| UI-004 | No structured user bug capture | Local flow implemented | Browser drafts and JSON download; shared triage backend remains future work |
| OPS-001 | Collector process does not persist reliably between sessions | Open | Durable deployment, supervisor and external monitoring needed; no uninterrupted-runtime claim |
| DATA-001 | No eligible live spot quotes under current configuration | Blocked | Approved feed access and runtime credentials required; no fabricated fills |
| OPTIONS-001 | Actual quoted options not executable | Open | Listed contract data, bid/ask connector and whole-contract execution required |

Report problems through `/bugs`. A downloaded report must be reviewed and submitted for shared triage; saving a browser draft does not notify maintainers.
