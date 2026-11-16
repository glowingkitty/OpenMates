# VS Code extension: history, fit, options and recommendation

Status: **draft research, nothing implemented.** Nothing here gets built
until the owner approves it. Written 2026-11-14 for TASK-3700. Facts come from
the dev checkout at `f040ceeaa0` and the chats working on agentic coding and
the Rust migration. The Plan is `plan.yml` in this folder. The draft
Specification `feature.vscode-extension` (pair login, connect folder, review
changes, privacy) is proposed in the session worktree. It moves to
`specifications/features/vscode-extension/` only after the owner approves it.

> **Update 2026-11-16:** the removed extension has been reviewed file by file in
> `old-extension-review.md`. The revised Plan **restores and reuses** its
> skeleton, bridge, CSP builder, pair-only rule, test harness and workflow, and
> lists only what changes.
>
> Since 14 Nov:
> - the Rust host runs commands (`56813a6f93`);
> - `remote-access --json` already prints lifecycle and request events;
> - a second host for the same folder is already refused.
>
> Dependencies 2, 3 and 6 below shrink to a small JSON addition, and the effort
> drops. The owner decides on 22 Nov.

## 1. Short answer

- Build it again, but **start the other way round** from last time. First make
  the open VS Code folder the Project's **connected machine** (Flow 2). The AI
  works in a per-chat Git worktree on that machine, and you review its changes
  in VS Code's own diff view. Chatting stays in the web app, the Apple apps and
  the CLI for now.
- Add a chat panel inside VS Code only in a second step. It would show the
  bundled web app's Project chat, not the whole app.
- Why this order: the connected machine already exists as a stable,
  client-side encrypted protocol with a Rust host
  (`packages/openmates-rust/src/source_host/`). The extension only has to start
  it and show its results, so we get no second code path, no new API and no
  new crypto. A webview copy of the whole app has three open problems:
  - The backend checks the request Origin, and a webview's origin is not on its
    allowlist.
  - Passkeys cannot work inside a webview.
  - The app would ship in a second release train.
- Rough effort, reusing the old code: **MVP about 6 to 8 agent-days, v1
  about 9 to 11 more**. The main outside dependency is public native binary
  builds (section 7).

## 2. History of the old extension

| When | Commit | What |
|---|---|---|
| 2025-02-05 | `63cdd71e1f` | First stub ("vscode specific files"). |
| 2026-07-04 | `c0ae0d1c9b`, `51a4aac0f3`, `b16c91f230`, `579db8c342` | Real build: `frontend/apps/vscode_extension`, Plan `docs/plans/vscode-extension-v1/plan.yml`, CI workflow `.github/workflows/vscode-extension.yml`. |
| 2026-08-02 | `328c22cb3e` | Live Project source browsing. |
| 2026-08-21 | `270b3b4f78` | Build heap fix for the bundled web app. |
| 2026-10-22 | `1051560ef4` | Removed: "Remove the unused VS Code client, its CI/build tooling and runtime adapter, eliminating its unpatched braces dependency chain." |

**What it did** (about 900 lines of TypeScript, 29 files):
- A webview panel (`extension.ts`, `webviewHtml.ts`) loaded a **bundled static
  build** of the full web app (`web_app/scripts/build-vscode.js`,
  `OPENMATES_BUILD_TARGET=vscode`). It did not load the live site, because
  production sends `X-Frame-Options: DENY`.
- It used a strict CSP with a nonce and allowed no frames.
- It had a small bridge (`bridge.ts`) with three message types from the app:
  open a file, show a proposed diff with `vscode.diff`, and copy text.
- Login was pair-only (`authMode.ts`). The webview never collected passwords,
  passkeys, 2FA codes or recovery keys.
- Project access was **read-only**. The webview told the user to run
  `openmates remote-access --path ./my-project` in a terminal.
- The web app had a `platform: 'vscode'` runtime adapter
  (`ui/src/platform/runtime.ts`), plus branches in `Login.svelte`.
- Tests: 21 unit tests (`node --test`), an Extension Host smoke under `xvfb`
  with `@vscode/test-electron`, and an installed-VSIX login smoke.

**Why it was removed:**
- It was internal and manual-test only, never published, and nobody used it.
- Its Plan was still `implementing`, with most acceptance criteria `pending`.
- The installed-VSIX login smoke was one of the "legacy workflows" that failed
  on purpose because nobody had migrated it.
- What finally removed it was a dependency audit: its build chain pulled in an
  unpatched `braces` version.

**What to reuse.** Don't revert the commit: the revert would also touch
`Login.svelte`, `svelte.config.js` and both lockfiles. Copy these instead:
- The test harness (`runTest.ts`, `runInstalledTest.ts` with
  `@vscode/test-electron` under xvfb) and the CI step order from
  `vscode-extension.yml`.
- The webview CSP and nonce builder, and the asset path rewriting
  (`assetPaths.ts` and its tests). These are only needed for the Phase 2 chat
  panel.
- The bridge message checks in `bridge.ts` and their tests, as the pattern for
  messages from the panel to the extension.
- The pair-only login rule.

**What not to reuse:**
- The read-only remote-access setup text. Remote access now writes files, runs
  commands and makes commits.
- The TypeScript CLI calls.
- The full-shell webview as the first product.

## 3. Fit with today's stack

**Connected machine (Flow 2).** This is the remote flow in
`docs/plans/agentic-tests-and-git-sync/plan.yml` (acceptance test A2), owned by
`docs/plans/native-agentic-coding-readiness` (packages R1 to R10).
- `openmates remote-access` holds a WebSocket to the backend. The backend only
  relays messages: `project_remote_access_register`, `_heartbeat` (every
  15 s), `_request`, `_complete`, `_disconnect` and `_revoked`.
- Operations: `list`, `search`, `read_text`, `read_*_chunk`, `create_file`,
  `update_file`, `copy_entries`, `move_entries`, `run_command`, `git_status`,
  `git_commit`, `git_land` and `create_source`. There is no push.
- Each chat gets its own worktree under `~/.openmates/worktrees/<source>/<chat>`
  on the hidden ref `refs/openmates/chats/<chat-id>`.
- Commands and Git writes need a single-use approval tied to a digest the
  client computes with the Project key, and they run in a sandbox (bubblewrap
  or AppArmor on Linux; Seatbelt on macOS is still planned).
- The host is Rust (`source_host/`, `client/source_host.rs`,
  `remote_access_crypto.rs`). The CLI shell for it is
  `openmates-tui-native/src/cli/remote_access.rs`.

**Encryption.**
- A connected machine is an ordinary logged-in client. It unwraps Project keys
  with the master key, or with the Team key for Team Projects.
- Remote file content is never stored on OpenMates.
- E2B sandboxes get no keys.
- An extension that starts this host adds no new crypto.

**Login.**
- `openmates login` uses pair login: OPAQUE over `/v1/auth/pair/v2/*`, approved
  in the web app under Settings > Developers > Devices
  (`client/pair.rs`, `docs/plans/pairing-pake-hardening/protocol.md`).
- The native CLI keeps its credential snapshot in the OS keyring, a local key
  file or a passphrase vault (`openmates-tui-native/src/storage.rs`).

**Rust core shells.**
- There are three: TUI/CLI (done), web (a wasm Worker built from
  `openmates-browser-bindings`, browser only) and Apple (UniFFI).
- `packages/openmates-session-bindings` also has napi, wasm and pyo3 builds.
  Pairing is still missing from them, and the publish workflow doesn't seem to
  ship the `.node` or wasm files.
- The web app still runs chat window, streaming, recovery and
  Projects/Tasks/Teams in TypeScript (`docs/migration/rust/capabilities.yml`,
  as of 2026-11-12).

**Projects maturity.**
- Projects is off in production (`backend_config.yml`; only the dev config
  turns it on).
- `feature.projects` v2 is approved.
- The agentic coding chat is finishing the Timeline tab and then two real
  example Projects, one of them on a connected machine. Flow 2 has not been run
  end to end yet.

**What this means for the extension:**
- The extension should **start the native `openmates` binary as a child
  process** (`openmates remote-access --path <folder>`) and talk to it through
  a machine-readable status stream.
- It should not link the core into Node. The binary is the reference shell, it
  already does pairing and stores keys, and every core fix reaches it first.
  Linking through napi would need pairing support and native builds for each
  OS that don't exist yet.

## 4. Options compared

| | A. Webview of the web app plus bridge | B. Thin client with its own chat panel | C. VS Code folder as the connected machine |
|---|---|---|---|
| What the user gets | The whole app in a VS Code tab; files, diffs and terminal through a bridge. | A native-looking chat in VS Code; core logic in Node or the CLI. | The AI edits and runs tests in this folder; you review diffs in VS Code. Chat happens in the web or Apple app (a panel comes later). |
| Second code path? | Yes: a second app build, `platform==='vscode'` branches, and a bridge doing file work beside the source host. | Yes: a second chat UI; embeds, approvals and settings rebuilt. | **No**: uses the existing source host and relay contract as-is. |
| Backend change | Origin allowlist must accept `vscode-webview://`, or all traffic is proxied through the extension. Security review needed. | None. | **None**. |
| Login | Pair only (passkey RP ID is `openmates.org`, so webviews can't use passkeys). Master key lives in the webview Worker. | Pair through the CLI or core. | **Pair through the CLI binary**, as `openmates login` does today. |
| Keys in VS Code | Webview storage plus SecretStorage via the bridge. Hardest to get right. | SecretStorage or the CLI vault. | **The CLI's passphrase vault in the extension's storage, with the passphrase in SecretStorage.** Keys never pass through extension JavaScript. |
| Reviewing changes | Bridge calls `vscode.diff` (old code). | Own UI. | **Native diff and a tree of the chat worktree's changes; Land and Discard buttons.** |
| Offline | Webview cache is unclear. | Depends. | Same as the CLI: closing VS Code takes the machine offline; AI jobs continue on the server and resume when it is back. |
| Forks (Cursor, Windsurf, VSCodium) | Works; big bundle. | The VS Code Chat API needs Copilot Chat and won't work in forks; a custom webview would. | **Works everywhere**: only stable APIs (commands, tree view, diff, SecretStorage, child process). |
| Remote windows (SSH, WSL, containers) | Workspace bridge needs care. | Depends. | `extensionKind: ["workspace"]` runs it where the files are; ships one VSIX per platform. |
| Size | Web bundle (tens of MB). | Small to medium. | Small extension plus the native binary (about 10 to 20 MB per platform; to be measured). |
| MVP / v1 effort | 3 to 4 weeks / 6 to 8 weeks | 3 to 5 weeks / 8 to 12 weeks (embed parity is large) | **About 2 weeks / about 4 weeks** |

**Marco's assumption, the webview plus bridge (A), is still the right way to
bring *chat* into VS Code later.** Building it first would mean:
- solving the webview Origin issue in the backend's auth (a security change);
- running the Rust web Worker inside a webview, which nobody has tested;
- keeping a second app build releasable.

It also gives no coding value that C doesn't, because the AI edits files
through the connected machine either way. So the plan builds **C first**, then
a **chat panel (a slim A)** that shows only the current Project's chats and
uses C for files.

## 5. Publishing and forks

- **Microsoft Marketplace** (`vsce publish`): its terms allow only Microsoft's
  VS Code builds to use it.
- **Open VSX** (`ovsx publish`; Eclipse publisher agreement plus namespace
  claim): used by Cursor, VSCodium, Windsurf, Gitpod and Theia.
  - Cursor sometimes shows new versions with a delay. Its forum lists known
    sync and search problems.
  - Open VSX launched a managed registry in April 2026, with Cursor among the
    first customers.
- Both registries accept **one VSIX per platform** (`--target linux-x64`,
  `linux-arm64`, `darwin-x64`, `darwin-arm64`, `win32-x64`). That is how the
  native binary ships.
- **Release channels**, mirroring `publish-cli.yml`:
  - pre-release VSIX from `dev`;
  - stable from `main`, after Projects is on in production;
  - tokens stored as GitHub secrets.
- The VSIX licence is AGPL-3.0-only, like the old package.
- The binary must not phone home beyond the OpenMates API it is configured for.

## 6. Testing on E2B: feasible and cheap

- **The full desktop template is not needed.** The existing `openmates-ci-runner`
  E2B template (`scripts/ci_e2b_runner.py`: Ubuntu 24.04, xvfb, ffmpeg, GitHub
  runner) has what headless VS Code UI tests need. The CLI terminal recordings
  already use `xvfb` plus `ffmpeg x11grab` (`scripts/cli_video_capture.py`).
- **What to add:**
  - a pinned VS Code build, cached in the template, or downloaded by the test
    runner;
  - `wdio-vscode-service` (WebdriverIO), which drives VS Code's own UI and
    reaches into webviews, which are nested iframes;
  - the old `@vscode/test-electron` harness for Extension Host tests.
- **The E2B desktop template** (XFCE plus VNC streaming) is worth it only to
  watch a run live or to let an agent click around. Keep it optional.
- **Proof video:** record with `ffmpeg -f x11grab` from the same display. Upload
  through `scripts/ci_evidence.py --upload` like the Playwright videos.
- **Comparison with `/dev/preview`:** this only makes sense for webview UI, so
  the Phase 2 chat panel. Each panel component is screenshotted at a fixed
  width and theme next to its `/dev/preview/<component>?chrome=0` page. They
  are compared by pixel diff with a threshold (VS Code adds its own theme
  variables, so the threshold must allow for that). Phase 1 uses only native
  VS Code UI, so its proof is screenshots and a video of the real flow.
- **Real-stack E2E (Phase 1):**
  1. Playwright logs a dev test account into the web app.
  2. The extension starts pairing.
  3. Playwright approves it in Settings > Devices.
  4. The extension connects the folder.
  5. A web chat asks for a file change.
  6. VS Code shows the change in the tree and the diff.
  7. Land puts it on the branch.

  The pairing step already exists as a pattern (`tests/cli-pair-login.spec.ts`).
- **Cost** (published E2B rates, $0.000014 per vCPU-second plus $0.0000045 per
  GiB-second; check the e2b.dev price page before budgeting):
  - a 4 vCPU / 8 GiB runner is about **$0.33 per hour**;
  - a 10-minute E2E run is about **$0.06**;
  - 30 runs a week is about **$2 a week**.
  - The template build is a one-off.
  - Runs count against the 70% E2B cap shared with CI overflow.

## 7. Dependencies and risks

1. **The native binary must be publicly built for five platforms**
   (client-core plan TASK-4; no release workflow yet). Owner: the Rust
   migration chat. Without it the VSIX can't bundle the binary.
2. **Commands in the Rust host: done** (`56813a6f93`, Rust host runs approved
   remote commands in the OS sandbox tier).
3. **Machine-readable status from `remote-access`: mostly done.**
   - `--json` already prints `remote_access_lifecycle` (connecting, connected,
     reconnecting, disconnected) and `remote_access_request` lines.
   - Still missing: a revoked event, the attached source ids per folder, the
     chat worktree list, and pairing output as JSON. That is a small Rust CLI
     addition.
4. **Projects is off in production.** Public release waits for it.
5. **Flow 2 hasn't been run end to end.** Its A2 acceptance run comes first; the
   extension builds on it.
6. **Two hosts for one folder: handled.** The host already refuses a second
   owner unless takeover is confirmed interactively. The extension shows that
   refusal.
7. **Risk: macOS sandbox for commands** (Seatbelt, R9) is still planned. On
   macOS, commands stay off until it lands.

## 8. Effort

Agent-days, one lane at a time, including tests and CI.

Revised 16 Nov: the restored skeleton, tests and workflow save about 2 days
(MVP now about 6 to 8 days, v1 about 9 to 11 more). The original estimates
were:

**MVP (Phase 1), about 8 to 10 days.** Extension skeleton and CI, child-process
host with a JSON status stream, pair login with the vault passphrase in
SecretStorage, connect and disconnect the workspace folder, status bar, a
"Chat changes" tree with native diff, "Open chat in browser", a Linux and macOS
VSIX, and the E2B UI test with video.

**v1 (Phases 2 and 3), about 10 to 12 more days.** Land and Discard from VS Code,
multi-root workspaces, SSH, WSL and container windows, all five platforms,
Marketplace plus Open VSX publishing. Then the chat panel (a slim webview of
the bundled Project chat) with `/dev/preview` comparison. The panel alone is
about half of that time.

## 9. Open questions for Marco (one decision each)

1. **Start with "VS Code is your connected machine" and add a chat panel
   later?**
   Recommendation: yes. It is the quickest useful version and needs no backend
   change.
2. **When the chat panel comes, should it show the whole app or only the
   Project's chats?**
   Recommendation: only the Project's chats; the full app stays in the browser.
3. **Login only by pairing (scan a code with your phone or browser)?**
   Recommendation: yes. Passkeys can't work inside VS Code anyway.
4. **Should VS Code be its own device in "Devices", separate from the terminal
   CLI on the same computer?**
   Recommendation: yes, so it can be revoked on its own.
5. **Should AI changes always wait for you to press "Land" in VS Code?**
   Recommendation: edits follow the Project's write mode, but landing on your
   branch always needs a click.
6. *(Resolved: the Rust host now runs commands.)*
7. **Publish to both stores (Microsoft and Open VSX) at v1, with pre-release
   files from dev until then?**
   Recommendation: yes. Public release only after Projects is on in production.

## 10. Coordination notes

- **Agentic coding chat (4b5c74d7):**
  - Working on the Timeline tab, then the two example Projects; Flow 2 not
    started yet.
  - The connected-machine contract above is what that chat is building on.
  - The extension adds no new operations; it needs only dependency 3 (status
    stream) and dependency 2 (commands in the Rust host).
- **Rust migration chat (b00dd345):**
  - Web on the Rust core by default, with TypeScript still present for some
    units.
  - The extension uses the native binary, so it doesn't wait on the web
    migration. Only the Phase 2 chat panel does.
  - It does need dependency 1 (public native binary builds).
- Direct messages to both chats failed (not reachable). Their current state was
  read from their transcripts. The open asks are listed in `plan.yml` under
  `dependencies`.
