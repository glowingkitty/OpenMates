# Approved workflow improvements R1, R2 and R4

The approved changes are published to `dev` through session `0e70`. The tracked
outcome is TASK-2804, with R1 TASK-2749, R2 TASK-2153 and R4 TASK-6707. R3 and
automatic remote workers remain outside this rollout.

## Backend preparation (R1)

The schema carrier advertised gzip-v2 while the consumer required gzip-v3. The
consumer correctly rejected it and repeatedly initialized Directus from scratch.
Producer labels now come from the executed schema contract. Consumers discover
`runtime-<content-key>` tags, resolve a same-repository immutable digest, and
validate its compatibility labels before reuse. Mutable legacy discovery is
disabled in normal workflows.

The original image publisher cancels older runs on each dev push. A separate
dev-only schema publisher now serializes publication by compatibility key without
canceling running producers. It checks the exact source SHA, reuses an already
verified compatible image, or builds and verifies a missing image in two fresh
consumers before publication. Release image publication keeps its existing
source and version identity requirements.

Startup evidence records schema mode and service durations without environment
variables, health-check output or secrets. The controlled cold execution of
`composer-workspace-layout.spec.ts` passed in
[run 37356953151](https://github.com/glowingkitty/OpenMates/actions/runs/37356953151):
compose readiness took 487.334 seconds, including 461.665 seconds of CMS setup.
The independent publisher then found a compatible keyed image in six seconds in
[run 37360392442](https://github.com/glowingkitty/OpenMates/actions/runs/37360392442).
The same browser spec passed twice with prepared schema reuse on two source
commits. Both receipts attest the selected spec, source and harness, healthy API,
and removal of disposable containers, volumes and private account files.

| Run | Source | Backend readiness | CMS setup | API starts after |
| --- | --- | ---: | ---: | ---: |
| [Cold 37356953151](https://github.com/glowingkitty/OpenMates/actions/runs/37356953151) | d902d69 | 487.334 s | 461.665 s | 471.672 s |
| [Warm 37362427975](https://github.com/glowingkitty/OpenMates/actions/runs/37362427975) | d902d69 | 44.396 s | 14.164 s | 25.723 s |
| [Warm 37361931398](https://github.com/glowingkitty/OpenMates/actions/runs/37361931398) | 08cfaa8 | 45.537 s | 10.334 s | 27.905 s |

Backend readiness improved by 90.9% and 90.7%. All three executions had schema key
`cbe7ae099fbde2f13ec33e3182a19a992fd9e596da08c254ee91bcd5b9f3eeb6`.
Both warm consumers resolved and validated immutable registry images; the
compatible key had been republished between their discoveries, so their image
digests differ. Each consumer pins its own verified digest.

These are backend startup improvements, not a 91% reduction of whole CI requests.
The warm jobs themselves took 302 and 331 seconds; preparation waits were 503 and
447 seconds. Frontend preparation, image transfer, browser setup and hosted
runner availability remain material workflow costs.

## Storage admission and retention (R2)

Worktree allocation, private CI candidate publication and artifact retrieval now
reserve allocation headroom under one canonical lock. Reservations are fenced
with process IDs and process start ticks, so a crashed owner or reused PID cannot
hold a reservation indefinitely. Existing free-space and worktree usage guards
remain in force.

The reviewed inventory counts physical inode blocks, including directories,
without following links or counting shared hard-linked dependencies twice:

| Managed category | Physical storage |
| --- | ---: |
| Worktrees | 35.00 GiB |
| Candidate artifacts | 1.68 GiB |
| CI results | 12.49 GiB |
| Currently eligible for cleanup | 0 GiB |

Cleanup retains failures, active owners, pending consumers, recovery patches and
undelivered evidence. It only removes delivered successful result payloads after
14 days or expired, integrated candidate patches after the additional retention
window, while retaining compact receipts and identity evidence. Worktree expiry
remains the sole worktree deletion owner.

Operators can inspect with `python3 scripts/sessions.py disk inventory --output
<new-manifest-path>` and opt into admission-triggered cleanup with `disk enable
--manifest <reviewed-manifest-path>`. `disk disable` reverses that opt-in. Each
automatic cleanup first saves a dry-run and rechecks the selected payloads.
Admission-triggered cleanup is now enabled after a fresh review with zero eligible
payloads. No current payload was deleted. Activation revalidation takes about 2.4
seconds by skipping worktree size walks while preserving all deletion decisions
and payload checks.

Unused Docker builder cache was removed under the existing coordination locks.
No source, recovery work, images, containers or volumes were deleted. The disk
still has roughly 34 GiB free; protected data limits further safe reclamation.

## Hosted CI admission (R4)

The user confirmed GitHub Free with 20 hosted jobs. The coordinator now admits
against that owner-wide ceiling, deducts competing hosted jobs from other
repositories and accounts for dedicated runners separately. Unknown occupancy
fails closed. A reserved quick-job slot is lent to other ready work when no quick
job is waiting. Existing durable dispatch intents, fairness, cancellation and
recovery remain in place.

Owner occupancy is cached and bounded; it is refreshed when ready work needs
admission, avoiding repeated scans while the queue is already dispatched or
waiting on preparation. Configuration cannot exceed the confirmed entitlement.
The named coordinator service was restarted under its queue lock, retaining all
5,261 durable queue rows.

A bounded 12-job live burst on `ef87372` completed successfully in about 250
seconds. Peak reservations were 12 and peak simultaneous executions were 11,
demonstrating admission above the previous ten-job ceiling. The source-attested
[representative run](https://github.com/glowingkitty/OpenMates/actions/runs/37359293421)
executed `backend/tests/test_bounded_message_window.py`. This validates the new
admission path; it does not claim a measured peak of 20 executing jobs.

## Verification

Focused runtime, schema, environment, coordinator, candidate, result, resource
budget and session tests passed. The final storage/result regression selection
passed all 94 tests; coordinator and service coverage passed all 40 tests. Scoped
deployments passed repository lint and specification checks. No checks were
waived, and product browser verification uses the isolated CI coordinator.

Two unrelated existing test failures were confirmed against the prior source:
the daily-AI dispatch classifier and a workflow-scope assertion about preparation
component bypass. They are outside the approved changes.
