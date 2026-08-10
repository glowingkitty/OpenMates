# Apple Chat Rendering Parity

Status: first executable slice  
Created: 2026-07-15  
Owner: Apple/web parity work

## Goal

Use the rendered web app as the product oracle for Apple chat rendering without
coupling SwiftUI to browser DOM implementation details. The first slice covers
loaded user chats in the chat sidebar for the shared test account. Later slices
should extend the same manifest-plus-screenshot contract to message bodies,
markdown, highlights, embeds, images, and interactive questions.

## Source Of Truth

- Web oracle spec: `frontend/apps/web_app/tests/chat-rendering-parity-oracle.spec.ts`
- Apple candidate test: `apple/OpenMatesUITests/ChatFlowRealAccountUITests.swift`
- Comparator: `scripts/compare_chat_render_parity.py`
- Runtime artifacts: `artifacts/chat-rendering-parity/`
- Broader inventory: `docs/architecture/apple/parity-matrix.md`
- Static audit: `scripts/apple_chat_parity_audit.py`

## Current Slice

Surface: `loaded-user-chats`

The web oracle logs into the test account, opens the sidebar, waits for chats to
load, captures a screenshot, and writes:

```txt
artifacts/chat-rendering-parity/web-loaded-chats-manifest.json
artifacts/chat-rendering-parity/web-loaded-chats-sidebar.png
artifacts/chat-rendering-parity/web-opened-chats-manifest.json
```

The Apple UI test logs into the same account, opens the chat panel, captures a
simulator screenshot, attaches a JSON manifest to the XCTest result, and writes
this file when `CHAT_RENDERING_PARITY_ARTIFACT_DIR` is set:

```txt
artifacts/chat-rendering-parity/apple-loaded-chats-manifest.json
artifacts/chat-rendering-parity/apple-opened-chats-manifest.json
```

The manifest intentionally contains visible UI facts, not secrets or message
plaintext. It includes loaded row count, visible titles, placeholder states,
category presence, row frames, required testability signals, and a short
non-secret hash of the test-account email so the comparator can reject mixed
CI/local account artifacts before reporting UI differences. The opened-chat
manifest opens the first 10 loaded user chats and records each rendered message's
role, normalized content hash, text length, block counts, embed counts, sender
name presence, thinking section presence, and streaming state. It avoids raw
message plaintext while still detecting role/order/content/rendering drift.

## Commands

Dispatch the web oracle through the test control plane:

```bash
python3 scripts/tests.py run -- --spec chat-rendering-parity-oracle.spec.ts
```

Pin the web oracle to a specific GitHub Actions test-account slot when comparing
against a matching numbered local Apple credential slot:

```bash
python3 scripts/tests.py run -- --spec chat-rendering-parity-oracle.spec.ts --account 1
```

Run the Apple candidate through the remote Mac wrapper:

```bash
CHAT_RENDERING_PARITY_ARTIFACT_DIR=artifacts/chat-rendering-parity python3 scripts/apple_remote.py test-ios --simulator "iPhone 17" --only-testing "OpenMatesUITests/ChatFlowRealAccountUITests/testPasswordOtpLoginLoadsRecentChatsForWebParityManifest"
```

Pin the Apple candidate to the same numbered local credential slot:

```bash
CHAT_RENDERING_PARITY_ACCOUNT_SLOT=1 CHAT_RENDERING_PARITY_ARTIFACT_DIR=artifacts/chat-rendering-parity python3 scripts/apple_remote.py test-ios --simulator "iPhone 17" --only-testing "OpenMatesUITests/ChatFlowRealAccountUITests/testPasswordOtpLoginLoadsRecentChatsForWebParityManifest"
```

Compare the manifests:

```bash
python3 scripts/compare_chat_render_parity.py --web artifacts/chat-rendering-parity/web-loaded-chats-manifest.json --apple artifacts/chat-rendering-parity/apple-loaded-chats-manifest.json
```

Compare opened-chat rendering for the first 10 loaded chats:

```bash
python3 scripts/compare_chat_render_parity.py --web artifacts/chat-rendering-parity/web-opened-chats-manifest.json --apple artifacts/chat-rendering-parity/apple-opened-chats-manifest.json --strict-order --minimum-overlap 10
```

Both manifests must be generated from the same test-account credential source.
The comparator checks `environment.account_email_hash` in both artifacts and
fails early when a GitHub Actions web oracle is compared to a local Apple run for
a different `.env` account. `--account N` only selects the GitHub Actions secret
slot; `CHAT_RENDERING_PARITY_ACCOUNT_SLOT=N` selects the matching local numbered
Apple credentials. The slot numbers must refer to the same actual account in both
credential stores.

Validate only the web oracle artifact when Apple output is not available yet:

```bash
python3 scripts/compare_chat_render_parity.py --web-only
```

Use stricter matching once Apple row identifiers and ordering are stable:

```bash
python3 scripts/compare_chat_render_parity.py --strict-order --minimum-overlap 5
```

## Acceptance Criteria

- Web oracle manifest validates with `--web-only`.
- Apple candidate manifest exists for the same test-account run.
- Comparator passes with at least one overlapping visible chat title.
- Opened-chat comparator passes for the first 10 loaded chats with matching
  message role sequence, normalized content hashes, and render block counts.
- Apple screenshot artifact shows the loaded chat panel, not an empty or loading state.
- No committed artifact contains credentials, auth tokens, message plaintext, or private machine paths.

## Next Slices

- Add stable Apple identifiers for chat-group headers, chat title text, metadata rows, unread badges, and category circles.
- Tighten loaded-chat comparison to group count, row ordering, pinned/unpinned sections, and hidden/show-more states.
- Add an active-chat transcript oracle for message roles, markdown blocks, highlighted ranges, embed type counts, image dimensions, and interactive question controls.
- Add screenshot comparison with masked dynamic regions for timestamps, status bars, cursors, and transient syncing indicators.
- Wrap the workflow in a dedicated OpenCode skill after this first slice proves useful across at least two parity tasks.
