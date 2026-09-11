# Chat failure emails

Official dev and production email the configured `SERVER_OWNER_EMAIL` (or `ADMIN_NOTIFY_EMAIL`) when the backend detects a terminal technical chat failure. Self-hosted servers exit before touching the limiter or mail transport. The existing trusted server-edition resolver controls this distinction; setting an environment label alone cannot enable the feature.

The AI worker classifies its terminal result, including generic error text inside a successful task envelope, and catches exceptions and technical timeouts. WebSocket dispatch/handler errors also notify. Expected credit, policy, and cancellation outcomes are excluded. Content is inspected locally and never included in the queue payload or email.

The separate email task receives only a one-way request fingerprint and allowlisted stage/category. A Redis Lua transaction marks a fingerprint seen for seven days, increments the day's failure count, and reserves one of five transport attempts. Keys are isolated by the actual server edition and UTC calendar day. Workers share the counter; restarting a worker does not reset it. Counter history expires after two days. Cache loss is a limitation; this is not durable disaster-recovery accounting.

Reservations are not refunded: missing configuration, rejected mail, and ambiguous transport outcomes may produce fewer than five emails, but automatic retries cannot flood the admin. The fifth attempt explains the cap. Suppressed failures remain counted and logged; they are not replayed at midnight. Worker logs distinguish queued, accepted, rejected, missing configuration, unavailable limiter, suppression, and unknown delivery. Accepted means accepted by the configured email service, not inbox delivery.

No Discord or OpenObserve dependency exists in this path. The existing email broker/worker remains necessary; a queue failure logs a content-free error and does not initiate another alert. The queue call is bounded from the caller's perspective, with worker deduplication protecting ambiguous submission. Existing independent infrastructure health alerts remain responsible for broker/worker outages and hard worker termination before Python cleanup can execute.

No REST endpoint, schema migration, billing access, or client change is introduced. Email contains environment, normalized stage/category, `BUILD_COMMIT_SHA` when valid, and daily counters. No chat/user IDs, raw exception details, prompts, response text, or ciphertext is emailed.

Verification: focused notification units and adjacent AI regression suites. E2E and live email delivery are explicitly skipped at the user's request on 2026-09-10. Dev source deployment does not imply a production rollout.
