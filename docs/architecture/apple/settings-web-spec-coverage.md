---
status: active
last_verified: 2026-06-11
---

# Apple Settings Web Spec Coverage

This matrix tracks how closely Apple settings tests reproduce the related web
Playwright settings specs. `Covered` means a native test exercises the same user
intent. `Native equivalent` means Apple uses the platform-native path instead of
browser-only DOM, localStorage, iframe, or Stripe assertions. `Fixture-only`
means the UI is deterministic and non-mutating but does not prove the live
backend mutation.

| Web spec | Apple coverage | Status | Next gap |
| --- | --- | --- | --- |
| `language-settings-flow.spec.ts` | `SettingsInterfaceLanguageParityUITests` opens Interface → Language, selects Deutsch, verifies selected state and translated UI, then resets to English. | Native equivalent | Add authenticated API persistence once live-account preference tests are enabled. |
| `interface-font-settings.spec.ts` | Interface page opens, but native font picker is not implemented. | Missing | Add native font setting UI and persistence. |
| `model-toggle-settings.spec.ts` | AI page opens only. | Missing | Add stable model toggle IDs and persistence test. |
| `default-model-settings.spec.ts` | AI page opens only. | Missing | Add default-model picker IDs and controlled chat assertion. |
| `ai-settings-breadcrumb.spec.ts` | AI page opens only. | Missing | Add model/provider details or native unsupported-state assertions. |
| `debug-logging-settings.spec.ts` | Privacy root opens only. | Missing | Rebuild debug-log settings with OpenMates primitives and IDs. |
| `focus-mode-settings.spec.ts` | Apps fixture opens focus detail, examples, process bullets, prompt toggle, mention inserted state. | Fixture-only | Expand fixture to exact Jobs/Deep Research scenarios. |
| `skill-weather-forecast.spec.ts` | Apps fixture opens Weather skill detail, provider/model/example cards, mention inserted state. | Fixture-only | Add native weather embed execution/fullscreen parity. |
| `skill-provider-icons.spec.ts` | Apps fixture checks provider rows exist. | Partial | Add provider icon/name/background assertions across metadata. |
| `mention-dropdown-settings-memory.spec.ts` | No native live memory CRUD or composer mention test. | Missing | Rebuild memories settings testability and add chat mention flow. |
| `reminder-button-settings.spec.ts` | Reminder public content tests exist, but not chat reminder settings flow. | Partial | Add chat reminder button → settings form → fired system message flow. |
| `settings-change-email.spec.ts` | Sensitive account smoke covers entry points only. | Fixture-only | Add reserved-slot live email roundtrip after credential injection is solved. |
| `recovery-key-settings.spec.ts` | Sensitive account smoke covers entry points only. | Fixture-only | Add reserved-slot recovery-key regenerate/login flow with redacted artifacts. |
| `backup-codes-settings.spec.ts` | Sensitive account smoke covers entry points only. | Fixture-only | Add reserved-slot backup-code reset/login flow with redacted artifacts. |
| `settings-buy-credits-stripe-eu.spec.ts` | Billing StoreKit fixture covers product rows and native fallback intent. | Native equivalent | Add StoreKit sandbox success/failure assertions. |
| `settings-buy-credits-stripe-managed.spec.ts` | Billing StoreKit fixture covers product rows and invoice empty state. | Native equivalent | Add native invoice/refund fixture states or StoreKit receipt reconciliation. |
| `settings-buy-credits-bank-transfer.spec.ts` | Billing fixture checks bank-transfer web-only fallback. | Native equivalent | Add amount/reference copy behavior if native owns it. |
| `settings-gift-card-bank-transfer.spec.ts` | Billing hub exposes gift-card row only. | Partial | Add gift-card buy/redeem native fallback test. |
| `settings-support-stripe.spec.ts` | Support page opens in shell only. | Missing | Add support one-time native/web-only flow test. |
| `settings-support-bank-transfer.spec.ts` | Support page opens in shell only. | Missing | Add bank-transfer support details/copy test if native owns it. |
| `settings-support-monthly.spec.ts` | No web spec found during audit. | Unmapped | Add web spec or define native monthly support contract. |
| `unauthenticated-app-load.spec.ts` | Public guest/app/settings smokes cover fragments only. | Partial | Split into public chat, daily inspiration, examples/embed fullscreen native tests. |

Recommended implementation order:

1. Safe preference tests: language, font, model toggles, default models, debug logs.
2. App Store examples and provider icon visual/testability expansion.
3. Reminder and memory CRUD/mention flows.
4. Reserved-account sensitive live flows.
5. StoreKit sandbox purchase/refund equivalents.
