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
