# Host disk coordination

One supervised metadata-only service owns disk grants and schedules approved
cleanup. Its private ledger at `~/.local/state/openmates/disk-coordinator` covers
registered repositories on the same host/filesystem. Linked worktrees resolve
through their Git common directory, so they cannot create independent budgets.
OpenMates Tasks remain authoritative for work status; the ledger owns capacity
tickets, leases and bounded diagnostics.

## Admission and recovery

`resource_budget.reserve` queues a named operation. The elected service grants it
atomically against available bytes, outstanding commitments and free inodes. The
client rechecks and claims the grant immediately before allocating. A chat tool
waits up to three seconds, then returns a durable disk wait with a checkpoint/yield
instruction. Its ticket survives process exit. Workspace creation and CI
publication use stable operation names. A completed operation's next invocation
creates a new cycle with fresh delivery identities.

The foreground Task adapter queues one version-fenced blocked status and activity
through its existing Task command outbox. The detailed disk reason appears in the
existing context view and host ledger; no product blocker enum or API is added.
Restoration requires the exact status/version produced by the acknowledged block
and no intervening user blocker. Queued writes remain pending until acknowledged.
Concurrent requests for one Task share a status fence and serialize ready events.

On pressure the service coalesces requests into one cleanup pass through existing
managed-payload, worktree, Docker and proof owners. It remeasures on the next tick
and reserves capacity before emitting `disk_ready`. The adapter rechecks owner
and grant, and reconciles uncertain starts instead of blindly resending. Human
pauses, deletion, archive, ownership changes and competing Task edits are preserved.
Other Task/CI events cannot wake a chat still waiting for disk capacity.

The existing 30 GiB floor has a 2 GiB recovery margin after pressure. Worktrees
retain their 85% ceiling; CI publication retains its absolute floor. Free inodes
have a separate 10,000 floor. Zero-progress cleanup backs off for five minutes;
admission still checks capacity each second so independently freed space is used
promptly. Oldest requests have priority with bounded bypass. Impossible peaks are
rejected before queueing. Only requests with reserved space can resume.

## Safe allocations and cleanup

Leases reserve future additional allocation. Writers without dependable
attribution retain conservative peak commitments. A live owner may report
cumulative materialized bytes, reducing only the unallocated commitment. Unclaimed
expired grants return to waiting. Claimed leases stay protected until their kernel
owner and owned process group are gone; PID reuse cannot release a live group.

For other known heavy commands use the monitored wrapper:

```sh
python3 scripts/disk_coordinator.py run --repository /path/to/repository \
  --bytes 2147483648 --operation named-build --write-path /path/to/output \
  -- your-build-command arguments
```

Execution waits for a committed child-owner record. The wrapper monitors the
reserve and specified output paths and only terminates its own process group at
the budget limit. Its crash cannot release capacity while a child keeps writing.
This is cooperative admission for integrated writers, not a quota on arbitrary
host processes. Cancelled commands use their application's checkpoint recovery.

Active work, unfinished source, containers, archives and undelivered proof remain
protected. Managed payloads retain reviewed opt-in and receipt revalidation.
Worktrees use existing 96-hour expiry and recovery snapshots. Docker removes unused
build cache and aged dangling images, preserving every tagged rollback candidate,
container, volume and network.

After cutover, manual/scheduled cleanup entry points queue maintenance. Only the
elected service passes its inherited owner-lock descriptor to cleanup children;
they retain that lock after parent exit. Pressure does not create another complete
inventory manifest for every rejected caller. Diagnostic events are bounded.

## Activation and rollback

Deploy to dev before installing the unit, so it references the canonical checkout
rather than an expiring task worktree:

```sh
python3 scripts/install_disk_coordinator.py --print
python3 scripts/install_disk_coordinator.py
python3 scripts/disk_coordinator.py enable --repository /path/to/canonical/repo \
  --cleanup managed --cleanup worktrees --cleanup docker --cleanup proof
python3 scripts/disk_coordinator.py status --repository /path/to/canonical/repo
```

Enable refuses active legacy reservations. Old independent callers must finish
before cutover. Point the foreground adapter to the same deployed source and
deliberately restart its foreground connection. No hook definitions change and
no new chat gets execution permissions. Only locally registered auto-wake owners
continue automatically. Disconnection retains tickets/events; cleanup service
lifetime is independent of the foreground connection.

For a long-disconnected adapter, set the repository's optional
`execution_not_before` Unix timestamp to the reviewed rollout boundary before
reloading it. Older pending notifications remain durable and visible at normal
context boundaries, but cannot automatically start historical work. Uncertain
starts still reconcile their original delivery identities. Fresh events retain
normal authorized continuation. Preserve existing registration and pause controls.

Linux uses a supervised user systemd service. Enable user lingering separately
only under existing host administrative policy if boot without login is required.
On macOS use the platform's existing supervisor for `serve`; no unverified launchd
installer is supplied. First rollout is on the Linux dev host.

`OPENMATES_DISK_STATE` or `--state-root` selects an isolated ledger. The repository
marker records its location and both admission and adapter follow it.

For rollback, pause event delivery, finish/reconcile claimed allocations, then run
`disk_coordinator.py disable --repository ...`. Disable refuses outstanding grants,
retains waits and returns to fail-closed admission without caller cleanup. Stop
the service after all registered repositories are reconciled. Preserve the ledger,
outbox and uncertain starts. Deleted disposable caches cannot be restored.

Verification uses isolated ledgers/processes for admission, retained waits, child
crashes, leader exclusion, expiry, backoff, human pauses, Task version conflicts
and duplicate/lost delivery. Never fill a shared filesystem to test pressure.
