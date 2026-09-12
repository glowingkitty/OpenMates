# Isolated Apple component previews

Use the Apple Debug preview host to inspect and interact with a single production
component using synthetic local state. It serves the same purpose as the web
`/dev/preview` routes: short, repeatable component checks before a full app flow.
These previews do not prove login, synchronization, provider delivery, or complete
web parity.

Build and install a **Debug iPhone or iPad Simulator app** before launching a
preview. Release and TestFlight builds omit these routes. Keep delivery outside
Simulator on TestFlight; do not install or launch a locally built macOS Debug app
over the user's installed app. Use the installed TestFlight app for final Mac
product-flow checks.

## Reference and implementation

The user-confirmed, rendered web component and state are the comparison reference
when available. Use its exact `/dev/preview/<component-path>?chrome=0` URL, with
non-default variant, props, theme, and width encoded in the URL. Inspect the actual
rendered structure and computed values, then compare the Apple component at the
same effective width and state. A registry mapping or passing parser test does
not establish visual approval. The current web fixture may cover a different
scenario; check it before treating it as the reference.

The user explicitly rejected the web search preview's legacy `mobile` variant:
normal web chats use the regular wide embed card on phones as well. Keep that
300-by-200 presentation across Apple devices; do not infer a tall card layout
from a fixture's name or a phone size class.

Once the component check passes, verify the changed behavior in its real parent
flow. An isolated preview cannot establish account loading, shell layout,
navigation, draft persistence, or scrolling through a real conversation.

The implementation is split between:

- `apple/OpenMates/Sources/DevPreview/DevPreviewLaunchConfiguration.swift`: exact
  routes, bounded JSON values, component registry metadata, and configuration
  identity.
- `DevComponentPreviewView.swift`: production component hosts, synthetic fixtures,
  supported prop validation, and local interaction state.
- `RootView.swift` and `OpenMatesApp.swift`: preview launch selection and parent
  runtime guards that skip account restoration, telemetry, notification
  permission, and normal app bootstrap. These guards support the new
  `.component` host's isolated actions; they do not establish isolation for
  unaudited legacy surfaces. A running product session cannot switch into a
  preview through a URL.

The complete configuration is `Hashable`. A configuration change recreates the
host with `.id(configuration)`, resetting text, navigation, and local actions.
Invalid requested previews display `dev-preview-error`; they never fall through
to normal account startup. The root launch guards are necessary even when the
component itself has no service dependencies.

## Available components

| Component | Variants | Supported props | Web component path |
| --- | --- | --- | --- |
| `composer` | `default`, `focused`, `filled`, `attachment`, `disabled`, `model` | `text`, `placeholder` | `enter_message/MessageInput` |
| `chat-header` | `default`, `loading`, `incognito`, `draft`, `long-title` | `title`, `summary`, `appId` | `ChatHeader` |
| `message` | `default`, `user`, `assistant`, `thinking`, `markdown`, `citations`, `streaming`, `streaming-long`, `streaming-reduced-motion` | `content`, `thinkingContent` for static variants; none for streaming fixtures | `ChatMessage` |
| `embed-preview` | `default`, `processing`, `error`, `cancelled` | none; complete web fixture | `embeds/web/WebSearchEmbedPreview` |
| `embed-fullscreen` | `default`, `processing`, `error`, `withNavigation`, `actions-code` | none; web search or local code fixture | `embeds/web/WebSearchEmbedFullscreen`; code action variant uses `embeds/code/CodeEmbedFullscreen` |
| `history` | `default`, `long`, `mixed`, `workspace` | none; 160-message mixed fixture, with actual panes for `workspace` | `ChatHistory` |
| `sidebar` | `default`, `guest`, `account`, `empty`, `dated` | none; production rows, title/message search, date grouping and local selection | `chats/Chats` |
| `welcome` | `default`, `empty`, `continuation` | none; continuation carousel only | `ActiveChat` |
| `login` | `default`, `email`, `password`, `otp`, `error`, `lookup-error`, `password-error` | none | `Login` |
| `signup` | `default`, `basics`, `error`, `loading`, `unavailable`, `confirm-email`, `secure-account`, `password`, `creation-uncertain`, `passkey`, `passkey-prf-error`, `passkey-cancel`, `passkey-uncertain` | none | `signup/Signup` |

The first host supports string props from this table and rejects unknown keys or
wrong types. The transport supports typed JSON for future component hosts; it
does not make arbitrary props meaningful. Isolated embeds currently require
`app=web`; `actions-code` selects a complete local code fixture explicitly.
History mounts the real bounded `ChatView` transcript with 160 synthetic messages.
Welcome mounts the production `WelcomeContinuationCarousel` and its filtering
policy; it does not yet represent the entire landing page. The real toast overlay
also exposes feedback from component actions such as Copy.

The history `workspace` variant composes the production transcript, embed
navigation, sidebar and settings pane layouts with eight messages. The separate
`long`/`mixed` fixture keeps 160 messages for bounded rendering and traversal;
workspace state tests need only enough history to retain a distinct anchor. Its local controls change width
and pane visibility without replacing the transcript. Use iPad landscape to
exercise the actual split, then narrow the fixture to 730 and 390 points. Verify
the selected child embed, settings destination, visible transcript anchor and
bounded history window survive the transitions. The settings fixture owns its
guest learning-mode state and rejects account operations; unsupported settings
destinations are disabled. Sidebar search disables offline content access.

Retained native scroll views may remain in XCUITest’s accessibility hierarchy
while hidden. Verify the actual pane is outside the visible workspace and its
actions are disabled/noninteractive; do not equate `exists` with visibility.
Close the sidebar with its production close button, reopen settings, and operate
the previously selected setting to prove both isolation and state restoration.

Window width and available chat width have different roles. The measured web
sidebar changes mode at 600 points, settings overlays at 1100 or below, and the
chat/embed split requires at least 1024 points after surrounding panes and
gutters. The split allocates 400 points to chat and a 10-point gap. Validate the
real parent layout too: an isolated container cannot establish app-shell parity.

Inline embed cards remain 300 by 200 points on phones and desktops. Fullscreen
search results use the web grid's separate maximum of 320 by 200; this grid rule
must not turn inline cards into a narrow or tall mobile variant.

Composer editing, attachment removal, and submission update local state. Header
navigation changes the local title. Message citations and embed cards use the
production controls to open and close fixture content. External-link actions are
intercepted. These new `.component` host actions must not save drafts, upload
files, send messages, create shares, run code, or start authentication. Curated
public fixture media may load through normal GET requests and use the normal
image cache; that rendering behavior is allowed and needed for visual parity.
This is isolation from account and product mutations, not a network-free
renderer. Keep real authentication and notification tests separate.

The streaming fixtures drive the production paragraph renderer with explicit
chunks. Check retained paragraph identity across appends, source hydration,
opening citations before finalization, viewport changes, and finalization. The
long variant includes references beyond 3,000 characters. Normal motion uses
the web's 220 ms tail fade; reduced motion retains the same semantic blocks.

Authentication fixtures use the actual form and signup state machine with a
local transport. They cannot send email, create accounts, or accept a real
agreement. Request counters support assertions about visible outcomes; they do
not prove server authentication or cryptographic interoperability.

Legacy surfaces remain available for their existing targeted tests:
`chat-opening`, `chat-opening-recording`, `chat-share`, `embed-share`,
`quick-capture`, `composer-embeds`, `composer-draft-edit`, and `embeds` (optionally
with an app slug). Legacy chat-opening, sharing, and menu routes have not been
audited for full isolation; do not treat their gallery or flow coverage as an
isolation guarantee. Prefer the new `.component` host for new checks.

## Launch contract

These forms select the same component:

```text
openmates://dev/preview/composer?variant=filled&theme=dark&width=390&height=844&chrome=0
openmates://dev/preview/component/composer?variant=filled&theme=dark&width=390&height=844
https://app.dev.openmates.org/dev/preview/enter_message/MessageInput?variant=filled&theme=dark&width=390&height=844&chrome=0
```

The HTTPS form is accepted as a configuration URL passed to the Debug app. It
does not imply that visiting the URL in a browser opens the Apple app.

| Input | Launch argument | Environment variable | Default / validation |
| --- | --- | --- | --- |
| Route | `--dev-preview` | `DEV_PREVIEW` | Component ID or legacy surface |
| Component with route `component` | `--dev-preview-component` | `DEV_PREVIEW_COMPONENT` | Known registry ID |
| Variant | `--dev-preview-variant` | `DEV_PREVIEW_VARIANT` | `default`; must belong to component |
| Theme | `--dev-preview-theme` | `DEV_PREVIEW_THEME` | `system`, `light`, or `dark` |
| Width / height | `--dev-preview-width`, `--dev-preview-height` | `DEV_PREVIEW_WIDTH`, `DEV_PREVIEW_HEIGHT` | Optional integer, 240–2560 points |
| Props | `--dev-preview-props` | `DEV_PREVIEW_PROPS` | JSON object; host validates supported fields |
| Embed app | `--dev-preview-app` | `DEV_PREVIEW_APP` | `web`; known app slug |
| Complete URL | `--dev-preview-url` | `DEV_PREVIEW_URL` | Use alone, without individual preview options |

URL query names are `component`, `variant`, `theme`, `width`, `height`, `props`,
and `app`; `chrome=0` is accepted and no configuration chrome is rendered. Encode
JSON props with a URL builder rather than hand-escaping them. JSON is limited to
10,000 UTF-8 bytes, eight nesting levels, 200 array entries, and 100 object keys.
Malformed JSON, duplicate URL/argument options, unknown options, route suffixes,
and unsupported variants produce an error surface.

Allowed URL origins are `openmates://dev`, HTTPS `app.dev.openmates.org` on its
normal port, and HTTP/HTTPS loopback development hosts (`localhost`, `127.0.0.1`,
`::1`). Credentials and fragments are rejected. Environment configuration takes
precedence over launch arguments; use one form per launch to avoid stale settings.

## Simulator workflow

Run from the repository root. Select an available iPhone or iPad Simulator ID
with `xcrun simctl list devices available`; boot it if needed. Keep all build and
result outputs inside the repository. Example setup and build:

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
export APPLE_PREVIEW_SIMULATOR_ID='<selected simulator UUID>'
export APPLE_PREVIEW_DERIVED_DATA="$PWD/.derivedData/component-previews"
mkdir -p "$PWD/.runtime/component-previews/tmp"
export TMPDIR="$PWD/.runtime/component-previews/tmp"

xcodebuild build -project apple/OpenMates.xcodeproj -scheme OpenMates_iOS \
  -configuration Debug -destination "id=$APPLE_PREVIEW_SIMULATOR_ID" \
  -derivedDataPath "$APPLE_PREVIEW_DERIVED_DATA" \
  -clonedSourcePackagesDirPath "$APPLE_PREVIEW_DERIVED_DATA/SourcePackages" \
  CODE_SIGN_IDENTITY=-
xcrun simctl install "$APPLE_PREVIEW_SIMULATOR_ID" \
  "$APPLE_PREVIEW_DERIVED_DATA/Build/Products/Debug-iphonesimulator/OpenMates.app"
```

Launch with arguments:

```sh
xcrun simctl launch --terminate-running-process "$APPLE_PREVIEW_SIMULATOR_ID" \
  org.openmates.app --dev-preview composer --dev-preview-variant filled \
  --dev-preview-theme dark --dev-preview-width 390 --dev-preview-height 844 \
  --dev-preview-props '{"text":"Plan a weekend in Berlin"}'
```

Or launch with environment values, passed through simctl's `SIMCTL_CHILD_` prefix:

```sh
SIMCTL_CHILD_DEV_PREVIEW=message \
SIMCTL_CHILD_DEV_PREVIEW_VARIANT=citations \
SIMCTL_CHILD_DEV_PREVIEW_THEME=light \
xcrun simctl launch --terminate-running-process "$APPLE_PREVIEW_SIMULATOR_ID" org.openmates.app
```

After launching in preview mode, change configuration without rebuilding:

```sh
xcrun simctl openurl "$APPLE_PREVIEW_SIMULATOR_ID" \
  'openmates://dev/preview/chat-header?variant=long-title&theme=dark&width=390&height=844&chrome=0'
```

Interact through XCUITest or the available simulator computer-use tool. Capture
synthetic component evidence; retain private account evidence only in protected
local artifacts. Do not run manual UI automation concurrently with an XCUITest.

## Focused verification and extension

Run parser tests and the focused component UI tests after relevant changes.
Choose a new result-bundle path for each run:

```sh
xcodebuild test -project apple/OpenMates.xcodeproj -scheme OpenMates_iOS \
  -configuration Debug -destination "id=$APPLE_PREVIEW_SIMULATOR_ID" \
  -derivedDataPath "$APPLE_PREVIEW_DERIVED_DATA" \
  -clonedSourcePackagesDirPath "$APPLE_PREVIEW_DERIVED_DATA/SourcePackages" \
  -resultBundlePath "$PWD/.runtime/component-previews/verification-01.xcresult" \
  -only-testing:OpenMatesTests/DevPreviewLaunchConfigurationTests \
  -only-testing:OpenMatesUITests/DevComponentPreviewUITests \
  -only-testing:OpenMatesUITests/ProgressiveMessagePreviewUITests \
  -only-testing:OpenMatesUITests/DevAuthFormUITests \
  -only-testing:OpenMatesUITests/DevSignupRuntimeUITests \
  CODE_SIGN_IDENTITY=-
```

The parser suite checks input equivalence, identity, validation, and legacy
compatibility. Add pure fixture tests for local state and action outcomes where
the host introduces such logic. For each component, cross-reference a shared
state/action contract with the actual web `*.spec.ts` scenario: starting fixture
and props, user inputs, visible state transitions, resulting output, keyboard
behavior, and overlay or navigation behavior. For example, the composer contract
must track `frontend/apps/web_app/tests/component-message-input.spec.ts` and its
minimized-to-expanded interactive scenario. A registry route is only a lookup;
it must not imply that this behavioral contract has been verified.

Use the controls' actual accessibility roles: signup consent controls are
switches. For fullscreen coordinate interactions, enable
`--ui-test-embed-presentation` and wait for `embed-presentation-state` to report
`ready` before reading button coordinates. This observes completion of the real
presentation animation. Do not disable animations or replace readiness with an
arbitrary sleep.

Implement the corresponding deterministic XCUITest using the same synthetic
inputs and expected transitions. Assert the actual production field contents,
enabled controls, visible overlay or destination, and resulting state, including
state reset after configuration changes. A callback-fired marker or preview
readiness identifier alone does not prove interactive parity. Record uncovered
web actions explicitly; do not label a subset as full component parity. Use
iPhone and iPad runs when responsive behavior differs, then verify the relevant
normal app parent flow. These commands describe verification; this document does
not certify a test run.

To add a component, extend the registry and typed host prop validation, provide
synthetic fixtures using its production renderer, and connect actions to local
state. Audit the component and its parent for implicit account, permission,
persistence, and mutating network effects; preserve curated public-media GETs
and normal image caching needed for faithful rendering. Add a focused interaction test and pair it
with the exact reviewed web state. Remove its planned status only when its real
isolated host exists. Keep release builds free of preview code.
