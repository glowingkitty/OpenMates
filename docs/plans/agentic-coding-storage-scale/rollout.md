# Storage archive operator rollout

The operator command is `/app/scripts/storage_rollout.py` inside the initialized API container. It opens the existing Directus and S3 services. `status` reads only aggregate counts and gate booleans. Every mutation requires an explicit command and a private, human reviewed, exact source receipt file. No command in this runbook has been run against shared or production data.

## Evidence and input

The running API container must expose its deployed 40 character `BUILD_COMMIT_SHA` (or `OPENMATES_BUILD_SHA`). Put a private JSON receipt in a read-only path visible **inside that container**, such as `/run/storage-rollout/receipt.json`. Do not store the receipt or rollback selector in the repository. The command refuses a source mismatch. It does not print receipt text, identities, ciphertext, or S3 locators.

The receipt has `schema: "agentic-storage-rollout-v1"`, an exact `operation`, `source_commit`, `profile` (`real` or `isolated-ci`), and `operator_review_receipt` in `reviewed:<source_commit>:<review-id>` form. `prepare-read` also needs `reader_receipt`; `configure-prune` needs that same reader receipt and a distinct `validation_receipt`. Each is a reviewed exact source ID. A `ci-` fixture receipt and `profile: "isolated-ci"` cannot authorize a real rollout. The isolated profile requires the exact disposable CI environment, including `OPENMATES_CI_ISOLATED=1`, `OPENMATES_STORAGE_CAPACITY_FIXTURES=true`, the CI storage endpoint, and `SERVER_ENVIRONMENT=development`.

For `prepare-read`, `checks` must contain a passed, exact source `evidence_id` for each of `regional_copy`, `web_reader`, `cli_reader`, `npm_reader`, `pip_reader`, `apple_reader`, `client_decryption`, `personal_authorization`, `team_authorization`, `shared_revocation`, `version_reconstruction`, and `rollback_drill`. For `configure-prune`, add `canonical_acknowledgement`, `authorized_delete`, `authorized_export`, `lifecycle`, `p7_zero_provider_calls`, and `p7_capacity_target`. Each check is an object with `passed: true`, `source_commit`, and an evidence ID of at least eight characters. The zero provider check additionally records `real_provider_requests: 0`, `provider_credentials: "absent"`, and `provider_network: "internal"`. The P-7 target check records at least 1000 `user_days`, 500 `simultaneous_executions`, 500000 `rounds`, 200000 `new_embeds`, and 1000000 `file_versions`. A reviewer must inspect the actual CI artifacts and supported client results before issuing the reviewed IDs; the command validates the receipt shape and exact source binding.

## Commands

All examples run **inside the initialized API container**. The API image includes the script; make receipt and selector files available there with restrictive permissions before invoking a mutation.

```sh
python /app/scripts/storage_rollout.py status
python /app/scripts/storage_rollout.py prepare-read --receipt-file /run/storage-rollout/read-receipt.json
python /app/scripts/storage_rollout.py configure-prune --receipt-file /run/storage-rollout/prune-receipt.json
python /app/scripts/storage_rollout.py pause --receipt-file /run/storage-rollout/pause-receipt.json
```

`prepare-read` updates both `chat_message_archive_rollout` and `embed_version_archive_rollout`, row `agentic-storage-v2`. It enables the verified reader, leaves pruning disabled, and sets `initial_cohort=true` for real data. Newly activated message segments and version rows then retain PostgreSQL ciphertext for 24 hours. It refuses to replace an already enabled prune gate; pause first. `configure-prune` requires matching readers and full P-7 evidence before enabling both prune gates. Per-page and per-version transactions still recheck regional copies, source identity, pending recovery, current head/recent window, and the elapsed buffer. The tool does not bypass these fences.

The database receipts are separate from worker environment switches. The archive copy, reader activation and prune workers remain off until their own switches are deliberately enabled in the applicable runtime. For versions these are `EMBED_VERSION_ARCHIVE_COPY_ENABLED`, `EMBED_VERSION_ARCHIVE_READ_ENABLED`, and `EMBED_VERSION_ARCHIVE_PRUNE_ENABLED`. For messages they are `CHAT_MESSAGE_ARCHIVE_COPY_ENABLED`, `CHAT_MESSAGE_ARCHIVE_READS_ENABLED`, and `CHAT_MESSAGE_ARCHIVE_PRUNE_ENABLED`. Each defaults off. The chat actor advances expired copy leases, read verifies bounded pages before activation, and prunes only after a fresh page verification. Do not set any prune switch before both receipt rows show `pruning_enabled=true` and the initial source-copy window has elapsed.

`status` returns only counts of copying, verified and reader active message segments; readable and pruned message pages; copied, reader active, pruned and stale version rows; and each rollout gate's booleans. Message pruning is counted on page rows; a segment becomes `pruned` after every page is pruned. Observe copy failures, regional replication, checksum failures, client cold-read latency, pending recovery, tombstones, and S3 availability in existing service monitoring. A failed read, corruption, incomplete acknowledgement, authorization regression, or capacity breach calls for `pause` with a reviewed `pause_reason` of `checksum_failure`, `reader_failure`, `recovery_failure`, `capacity_failure`, `manual_pause`, or `other`. Pause turns pruning off in both rollout rows and records the reason. It deliberately leaves S3 reads enabled because already pruned rows still depend on their verified objects. Also disable the worker prune switches through the authorized runtime configuration process; do not turn off archive reads or purge S3.

## Bounded page rollback

For a specifically authorized archived message, create a private selector JSON with exactly `user_id`, `chat_id`, and `client_message_id`. Compute `selector_sha256` as SHA-256 of that JSON serialized with sorted keys and compact separators, and place it in a `restore-page` receipt with the same source/review fields. This binds approval to one page lookup. From the repository root, compute it locally without putting IDs on a command line:

```sh
python -c 'import json,sys; from pathlib import Path; from scripts.storage_rollout import selector_digest; print(selector_digest(json.loads(Path(sys.argv[1]).read_text())))' /private/selector.json
```

After the reviewed receipt and selector are mounted in the API container, run:

```sh
python /app/scripts/storage_rollout.py restore-page --receipt-file /run/storage-rollout/restore-receipt.json --selector-file /run/storage-rollout/selector.json
```

The command calls `ChatArchiveMutationService.promote_for_message`; it checks the current owner, looks up at most the selected page, verifies every S3 ciphertext record and the original source checksum, restores the bounded page in PostgreSQL through `restore_and_retire_page`, and only then activates the prepared regional S3 deletion tombstones. An unpublished page uses its fenced abort path. A response reports only whether one page was promoted. Repeat with a separately reviewed selector for another page. This path intentionally retires an archived page after verified restore; it does not provide an unbounded whole-chat restore.

Version rollback is limited to pausing further pruning and retaining regional S3 reads for already pruned versions. There is no operator command here that recreates pruned PostgreSQL version ciphertext; repair the verified S3 replica and client reader before resuming. Do not disable archive reads while any pruned version or message page remains.
