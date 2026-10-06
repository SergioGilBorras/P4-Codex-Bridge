# Concurrency

The bridge controls technical capacity only. The Orchestrator remains responsible for business scheduling.

`RuntimeLimits` separates global turns, app-server turns, exec processes, active threads, pending queue size and per-profile active turns. All values are positive integers. A single SQLite claim transaction enforces the active slot and workspace lock, including when two manager processes accidentally attempt dispatch at once.

The workspace policy is `READ + READ = allowed`; `WRITE` conflicts with every other lock on the same workspace. A write to a different workspace can proceed concurrently when global/backend/profile limits permit. The scheduler reports the first deterministic limiting reason and, for workspace conflicts, the blocking run ID.

App-server turn execution concurrency is a bridge policy, not an assumption that Codex supports unlimited turns. The default app-server limit is one for the current runtime manager; configure higher limits only after protocol/runtime validation. Exec concurrency has its own limit. Queued prompts persist until claimed and should be treated as sensitive local state.

The fake 50-job scheduler stress test checks capacity, workspace exclusion, unique claims, FIFO progress and eventual completion without calling Codex.
