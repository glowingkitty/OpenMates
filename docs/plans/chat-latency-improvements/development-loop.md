# Chat latency development loop

The real AI and latency measurements run on development: TUI first, then web. Selected Mate must appear within 1,500 ms; an ordinary factual answer must begin streaming within 2–3 seconds. The latency outcome remains open.

The isolated recovery regression was caused by the deployed tooling checkout launching an AI worker that consumed only `app_ai`. The candidate had already added `app_ai_routing`, but the workflow executed the older tooling file. The captured routing queue grew from one to two tasks with zero consumers. A separate read-only development probe found one routing consumer with the stage-one task registered and empty queues; this does not establish recovery or latency acceptance.

## Retained preparation timing

Preparation run 38391015631 took 918 seconds (15m18s). Schema creation took 492 seconds, web build 156, image reuse 64, fresh schema verification 40, private upload 37, CLI build 25, manifest generation 18, dependency installation 14 and source checkouts 14. Remaining steps and rounding account for the balance. Whole-commit preparation keys rebuilt unchanged inputs after a test-only edit.

## Required short loop

Publish the reviewed tooling before testing its effective worker configuration. The dedicated `backend-probe` mode reconstructs exact source, requires compatible published images and sanitized schema, starts and verifies the internal fixture stack, then performs bounded worker/broker/Redis/CMS checks. It skips Node/package installation, web and CLI builds, browser installation, signup and Playwright. Cache misses fail visibly before stack startup; no cold build or external provider fallback is allowed. Private raw stdout/stderr are retained with restrictive permissions. Receipts distinguish diagnostic health from recovery E2E and latency proof, and require verified cleanup.

A warm diagnostic should take 2–3 minutes; this target has not been measured. Preserve passing results when product and test dependencies match. After two failures require new evidence before reproducing. Keep fresh session, ownership, encryption, recovery and execution checks. Once the consumer is verified, rerun the affected recovery behavior, then deploy the processing candidate and measure ordinary TUI requests before web. Focus-mode and remote-access Project scenarios follow only after ordinary timing acceptance.

Development-loop Task: `517a3171-eb8b-46ad-9dae-2300d679686e`; general latency Task: `TASK-4979`.
