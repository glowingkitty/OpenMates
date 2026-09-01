# Apple Web Spec Recreation Gap Audit

Status: draft  
Created: 2026-06-10  
Session: 3725

## Summary

The current web suite has 167 Playwright `*.spec.ts` files. The Apple app has 12 XCTest files that directly exercise native app behavior, plus several Plans already tracking Apple parity work.

Fresh static inventory from `scripts/apple_parity_audit.py` found:

| Signal | Count |
| --- | ---: |
| Web Playwright specs | 167 |
| Web unique `data-testid` values | 498 |
| Apple unique accessibility identifiers | 57 |
| Shared web/Apple identifiers | 26 |

`scripts/apple_chat_parity_audit.py` currently fails because `chat-item-wrapper` is no longer detected in `apple/OpenMates/Sources/Shared/Components/ChatListRow.swift`.

## Existing Apple Coverage

These Apple XCTest files already cover part of the web spec surface:

| Apple test file | Covered surface |
| --- | --- |
| `apple/OpenMatesUITests/ChatFlowParityUITests.swift` | Seeded chat hierarchy, message bubbles, composer presence, no default table chrome |
| `apple/OpenMatesUITests/ChatFlowRealAccountUITests.swift` | Live dev login, create chat, receive assistant response |
| `apple/OpenMatesUITests/ChatOpeningScalabilityUITests.swift` | Large chat bounded opening |
| `apple/OpenMatesUITests/ChatResponsiveParityUITests.swift` | Chat responsive metrics |
| `apple/OpenMatesUITests/ChatShellResponsiveParityUITests.swift` | Sidebar/shell responsive behavior |
| `apple/OpenMatesUITests/MessageInputAttachmentUITests.swift` | Seeded attachment composer structure |
| `apple/OpenMatesUITests/MessageInputAudioRecordingUITests.swift` | Seeded audio recording composer structure |
| `apple/OpenMatesUITests/EmbedRenderingParityUITests.swift` | Debug embed gallery smoke coverage |
| `apple/OpenMatesUITests/BackgroundChatNotificationUITests.swift` | Simulated background notification |
| `apple/OpenMatesTests/ChatSyncParityTests.swift` | Chat sync data model parity |
| `apple/OpenMatesTests/SubChatProcessingTests.swift` | Sub-chat payload and context contracts |
| `apple/OpenMatesTests/ChatWindowLoadingTests.swift` | Bounded chat window logic |

Existing Plans already cover these Apple parity tracks:

| Spec | Surface |
| --- | --- |
| `docs/plans/apple-ui-contracts/plan.yml` | Web contract extraction and first composer parity pipeline |
| `docs/plans/apple-responsive-shell-parity/plan.yml` | Responsive shell/chat layout parity |
| `docs/plans/apple-chat-opening-parity/plan.yml` | Chat opening and bounded loading parity |
| `docs/plans/apple-embed-rendering-parity/plan.yml` | Embed preview/fullscreen parity |
| `docs/plans/apple-example-chat-visual-parity/plan.yml` | Example chat visual parity |
| `docs/plans/apple-sub-chat-focus-parity/plan.yml` | Sub-chat and focus-mode parity |

## Missing Or Not Yet Recreated Web Specs

The following groups are not yet represented by a focused Apple implementation/testing Plan. New Plans were created for each group.

| New spec | Web spec group to recreate in Apple |
| --- | --- |
| `docs/plans/apple-auth-security-parity/plan.yml` | Signup, login, recovery key, backup code, passkey, 2FA reconnect, account recovery, session revoke, security/location checks |
| `docs/plans/apple-settings-billing-parity/plan.yml` | Settings preferences, default/model toggle, language/interface, newsletter/report issue, billing, credits, gift card, invoices, referral, admin/free-testing visibility |
| `docs/plans/apple-chat-management-sharing-parity/plan.yml` | Chat search, context actions, hidden/show-more/pinned chats, share/import/export, fork/explain, copy, highlights, PII, incognito, paste classification, interactive questions, projects |
| `docs/plans/apple-reminders-public-content-parity/plan.yml` | Reminders, daily inspiration, demo/example/public/legal chat entry points and native notification scheduling boundaries |
| `docs/plans/apple-skill-application-parity/plan.yml` | Skill-specific outputs, application previews, code/PDF/image/file flows, code-run details beyond generic embed chrome |

## Verification Standard

Each new spec requires remote Mac verification through `scripts/apple_remote.py`:

```bash
python3 scripts/apple_remote.py status
python3 scripts/apple_remote.py build-ios --simulator "iPhone 17"
python3 scripts/apple_remote.py test-ios --simulator "iPhone 17" --only-testing OpenMatesUITests/<TargetTestClass>
python3 scripts/apple_remote.py cleanup --simulator booted
```

Specs that need iPad layout evidence also require:

```bash
python3 scripts/apple_remote.py test-ios --simulator "iPad Pro 13-inch (M5)" --only-testing OpenMatesUITests/<TargetTestClass>
```

Committed evidence must remain sanitized: no hostnames, IPs, usernames, private emails, raw account ids, local Mac paths, screenshots with private data, or secrets.
