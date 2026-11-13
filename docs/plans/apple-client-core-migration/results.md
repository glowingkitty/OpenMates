# Apple client core migration: measurements

All numbers come from `OpenMatesTests/NativeEncryptedSyncPerformanceTests` on a
GitHub `macos-26` runner (iPhone 17 simulator), synthetic encrypted fixture:
600 chats with wrapped keys and four encrypted metadata fields, one chat with
1000 encrypted messages. Median of 3 runs; `min` in brackets.

## A0 baseline: current Swift path

Run https://github.com/glowingkitty/OpenMates/actions/runs/42850250569
(CI job 4d080f3d, source 5c7d90a6).

| Phase | Items | Median ms (min) | Per item |
|---|---|---|---|
| chat_key_bulk_load | 600 keys | 157 (151) | 0.26 ms |
| chat_list_metadata_decrypt | 600 chats | 190 (187) | 0.32 ms |
| persist_chats (SwiftData) | 600 chats | 1188 (1183) | 1.98 ms |
| persist_messages (SwiftData) | 1000 messages | 892 (776) | 0.89 ms |
| cold_load_from_disk | 20 startup chats | 36 (35) | |
| chat_open_window_decrypt | 50 messages | 109 (88) | 2.2 ms |
| chat_open_full_1000_decrypt | 1000 messages | 1582 (1426) | 1.58 ms |

Reading: the isolated crypto and storage steps cost a few seconds at most for
this account size, all of it on the main actor. They do not explain the 14 to
17 s cold starts recorded in `docs/plans/apple-daily-use-recovery/plan.yml`;
those come from the sync pipeline around them (serial per-frame handling, double
JSON decode, session validation before the socket connects, repeated REST loads
and repaints), which this test does not exercise. A4 needs an end-to-end
measurement in addition to these phases.

## A1 bridge: first build with the core linked (not a comparison)

apple-unit run https://github.com/glowingkitty/OpenMates/actions/runs/42930687752
(source db09baad): the iOS app built and linked with the Rust core library;
`OpenMatesCoreBridgeTests` 7/7, `PasswordV2KDFTests` 5/5, the baseline test
passed again. The same Swift code as A0 measured about half the A0 times on
this runner (for example chat_list_metadata_decrypt 109 ms against 190 ms,
persist_chats 827 ms against 1188 ms).

Consequence: runner speed varies by about a factor of two between CI runs.
Before/after comparisons are only valid inside one run, so from A3 on the test
measures the old and the new path in the same process.

## A3a: batched decrypt through the core (2026-11-11)

Run 42947156839 (apple-unit, macos-26 simulator, candidate e85c9109). Old Swift
sequence and core calls measured in the same test process, median ms.

| Phase | n | Swift (old) | Core (new) | Change |
|---|---|---|---|---|
| chat key bulk load | 600 | 65 | 80 | 1.2x slower |
| chat list metadata decrypt | 600 | 203 | 24 | 8.5x faster |
| chat open, window decrypt | 50 | 86 | 49 | 1.8x faster |
| chat open, full 1000 decrypt | 1000 | 1384 | 786 | 1.8x faster |

Storage phases in this run (still Swift, unchanged): persist_chats 1226,
persist_messages 865, cold_load_from_disk 36.

Open: the core message and key phases cost about 130 microseconds per item,
against about 8 per metadata field. Where that time goes is not explained yet.

## A3a follow-up: where chat open time goes (2026-11-11)

Run 42955959638 (apple-unit, candidate d17fce83), same process, median ms.

| Phase | n | Swift (old) | Core (new) |
|---|---|---|---|
| chat key bulk load | 600 | 76 | 25 |
| chat list metadata decrypt | 600 | 223 | 22 |
| chat open window, store load only | 50 | 10 | 10 |
| chat open window, decrypt only | 50 | 67 | 31 |
| chat open full, store load only | 1000 | 130 | 130 |
| chat open full, decrypt only | 1000 | 1289 | 656 |

Key bulk load: per-key fingerprint formatting and one notification per key
removed (one notification per batch). Rust alone needs about 17 ms for the
1000 messages (Linux release benchmark `rust_cost_of_the_swift_perf_phases`),
so about 640 ms of the core decrypt-only phase is Swift work in
`ChatViewModel.decryptMessagesForDisplay`; not yet located.

## A3a follow-up 2: one render rebuild per decrypted message (2026-11-11)

Run 42959964856 (apple-unit, candidate 1db90c02; a faster runner than the runs
above, so compare within this run only), median ms.

| Phase | n | Swift (old) | Core (new) |
|---|---|---|---|
| chat key bulk load | 600 | 35 | 14 |
| chat list metadata decrypt | 600 | 99 | 14 |
| chat open window, decrypt only | 50 | 34 | 10 |
| chat open full, decrypt only | 1000 | 751 | 206 |
| chat open full, store load + decrypt | 1000 | 831 | 282 |

Split of the core decrypt-only phase: build records 0, core call 20, mapping
results back into `Message` 182. The mapping is one markdown parse per message
(`ChatHistoryRenderDocument.build`); before this change the decrypt path
triggered it once per field set (up to four times per message).
