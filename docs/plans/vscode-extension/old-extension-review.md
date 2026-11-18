# The removed VS Code extension: review and reuse map

Status: draft for the owner's decision on 22 Nov 2026 (TASK-3700). Nothing is
restored to dev yet.

The code was restored from `1051560ef4^`, the parent of the removal commit,
into a private scratch copy. The checks against today's code used `dev` at
`74049fba0b`.

## 1. What existed

**`frontend/apps/vscode_extension`**: 29 files, about 1,900 lines including
tests.

| File | Lines | Job |
|---|---|---|
| `src/extension.ts` | 358 | Commands `OpenMates: Open`, `Check Remote Access Setup`, `Show Logs`. Opens one webview panel. Handles bridge messages. About 150 lines are a CI-only login smoke. |
| `src/bridge.ts` | 152 | Typed webview messages: `openFile`, `showDiff`, `copyText`, `reportReady`. Paths must be relative with no `..`. Text up to 2 MB. Explicit forbidden list: `applyPatch`, `writeFile`, `runCommand`, `installPackage`, `runTests`, `gitCommit`, `gitPush`. |
| `src/webviewHtml.ts` | 219 | Webview HTML with a strict CSP (nonce scripts, no frames, `connect-src` limited to the API). Either loads the bundled app's `index.html` with rewritten asset links, or a bootstrap page with the setup text. |
| `src/assetPaths.ts`, `src/authMode.ts`, `src/state.ts` | 81 | Safe asset path segments. Pair-only login list. Reconnect policy (the extension never owns long-running work). |
| `media/openmates-vscode.js` | 55 | Webview script: posts `reportReady`, runs the CI login smoke. |
| `scripts/prepareWebAppBundle.mjs` | 49 | Copies the web app's static build into `media/app`. |
| `src/test/*`, `test_driver/` | 191 | `@vscode/test-electron` Extension Host test, plus an installed-VSIX test that installs the packaged file into a fresh profile. |
| `tests/*.test.ts` | 339 | 21 `node --test` unit tests: bridge, CSP, assets, auth mode, runtime config, state. |

**Outside the extension folder:**
- `web_app/scripts/build-vscode.js` (80 lines): `vite build` with
  `OPENMATES_BUILD_TARGET=vscode`.
- A `svelte.config.js` branch: `adapter-static` and relative paths for that
  target.
- `ui/src/platform/runtime.ts` (49 lines): reads `#openmates-vscode-config`.
- `Login.svelte`: starts on the `pair-initiate` step and stays there in VS Code.
- `scripts/audit_vscode_extension_v1.py` (133 lines): fails if anything that
  writes is exposed.
- `.github/workflows/vscode-extension.yml` (93 lines):
  1. validate the Plan;
  2. run the audit;
  3. run the CLI remote-access contract tests;
  4. run the unit tests;
  5. build the extension;
  6. build the web bundle;
  7. run the Extension Host smoke under `xvfb`;
  8. package the VSIX;
  9. run the installed-VSIX smoke;
  10. upload the VSIX artifact.
- `docs/plans/vscode-extension-v1/plan.yml` (900 lines; status `implementing`).

## 2. How it connected

It had **no OpenMates connection of its own.**
- The bundled web app inside the webview was meant to talk to the API directly
  (`connect-src` lists the API hosts), with the usual web login and sync.
- Project files came from a **separately started TypeScript CLI**
  (`openmates remote-access --path ./my-project`). That bridge could only read.
  The extension only showed that command as setup text.
- The extension itself did no remote access, no CLI calls and no crypto.

## 3. State and quality

**What was good:**
- Clean, small, documented modules with strict input checks.
- A strict CSP, and no relaxing of production frame headers.
- Pair-only login as a firm rule.
- Real VS Code tests in CI, including installing the packaged VSIX.

**What was never proven.** Old Plan acceptance status:
- AC-1 (full app shell renders), AC-2 (pair-only), AC-4 (Projects UI) and AC-5
  (open file and diff) were all `pending`.
- Assumptions A-1 ("webviews can host the bundled app") and A-2 ("pair login
  works there") were `unchecked`.

**Gaps found in the code:**
1. **The bundled app never loaded in an installed VSIX.** Commit `b16c91f230`
   switched the installed smoke to the bootstrap page "to avoid Electron
   installed-mode webview document blocking". So CI passed without the real
   app.
2. **The "login smoke" was not pairing and not in the webview.** It did a
   password login with a TOTP code from Node in the extension host
   (`runLoginSmoke`, `generateTotp`), sending a spoofed `Origin` header. That
   contradicts the pair-only rule it was meant to prove.
3. **Nothing in the web app called the bridge.** `git grep` at
   `1051560ef4^` finds no `showDiff`, `openFile` or `acquireVsCodeApi` caller
   in `frontend/packages` or `web_app/src`. The diff and open-file features
   could not be reached.
4. **Workspace matching used names.** It compared `sourceId` with the folder
   name and used only `workspaceFolders[0]`, so it was wrong for multi-root
   windows and same-name folders.
5. It was removed in a dependency audit because its tool chain pulled an
   unpatched `braces`.

## 4. What is now out of date

| Then | Now | Effect |
|---|---|---|
| TypeScript CLI, read-only bridge | Rust host `source_host/`: writes, `run_command` in the OS sandbox (`56813a6f93`), per-chat worktrees, `git_status`, `git_commit`, `git_land` | Setup text and the write-blocking audit are wrong. Review and Land are now possible. |
| Web app with TypeScript sync | Web app on the Rust core in a Worker. The loader refuses a page whose `window.location.origin` doesn't match the production bootstrap (`rustCoreLoader.ts:55`). | The old bundled-app approach can't start today's core in a `vscode-webview://` page without new work. |
| Backend Origin check | Allowlist; no `vscode-webview` origin (`auth_utils.py`) | Webview API calls would be rejected. |
| `adapter-static` branch in `svelte.config.js` | Removed; `svelte.config.docker.js` still uses `adapter-static` | The build target can come back from the docker config pattern. |
| `Login.svelte` pair-only switch | `pair-initiate` step still exists | The small pair-only patch can be reapplied. |
| Remote access in a terminal only | `openmates remote-access` has `--json` (lifecycle and request lines), `--project` and `--write-policy` for non-interactive use, `--enable-commands`. It refuses a second owner without interactive takeover. | Most of what the extension needs from the host already exists (section 5). |

## 5. Reuse map

| Old part | Decision | Change needed |
|---|---|---|
| `package.json` | Reuse | Public publisher metadata, icon, `extensionKind: ["workspace"]`, commands and views for sign in, connect, chat changes, land and discard. One package per platform with the native binary. Current `@vscode/vsce`, plus `ovsx`. |
| `extension.ts` skeleton (activate, Output channel, commands, `resolveWorkspaceFile` path guard, `inferLanguage`) | Reuse | Delete the password/TOTP smoke (about 150 lines). Add a small host process manager that runs `openmates remote-access --json …`. Map folders to sources by the attachment id the binary reports, not by name. Support all workspace folders. |
| `bridge.ts` and tests | Reuse in Phase 3 (chat panel) | Keep the allowlist and the forbidden list. File writes still go only through the source host, never the bridge. Change `showDiff` to open the worktree file against the target branch instead of taking text from the page. |
| `webviewHtml.ts` CSP, nonce and escaping, `assetPaths.ts`, and tests | Reuse in Phase 3 | Update the setup copy (no "read-only"). |
| `authMode.ts` and tests | Reuse | Unchanged rule; sign-in now runs through the binary's pairing. |
| `state.ts` reconnect policy | Reuse | Unchanged: the extension owns no long-running work. |
| Test harness (`runTest.ts`, `runInstalledTest.ts`, `test_driver/`) | Reuse | The installed test pairs through the binary instead of a password, and runs the real panel, not the bootstrap page. |
| `media/openmates-vscode.js` | Drop | It was only the smoke script. |
| `prepareWebAppBundle.mjs`, `build-vscode.js`, `runtime.ts`, `Login.svelte` patch | Phase 3 only, rework | They must solve the Rust core origin check and the backend Origin allowlist first. Build only the Project chat route, not the whole shell. |
| `audit_vscode_extension_v1.py` | Replace | New audit: the extension has no transport, crypto or credential code (it only starts the binary), no secrets in settings or logs, and the bridge has no write messages. |
| `vscode-extension.yml` workflow | Reuse the structure | Drop the TypeScript CLI tests and the web bundle (until Phase 3). Add a binary download per target, the real-stack E2E, `vsce package --target …`, and publishing jobs for the Marketplace and Open VSX. |
| `docs/plans/vscode-extension-v1/plan.yml` | Don't restore | Replaced by `docs/plans/vscode-extension/plan.yml`. Its AC-3, AC-6 and AC-7 ideas carry over. |

**How to restore** (after the owner's decision): `git checkout 1051560ef4^ --`
on the files marked Reuse into a feature session, then apply the changes above.
Don't do a full revert, because it would also bring back the old lockfiles and
the `svelte.config.js` branch.

## 6. Needed only for Cursor, Windsurf, VSCodium and Open VSX

- A publisher namespace on open-vsx.org, the Eclipse publisher agreement, and
  an `OVSX_PAT` GitHub secret. Publish the same per-platform VSIX files with
  `ovsx publish --target …`.
- No Microsoft-only APIs: no Copilot Chat participant, no proposed APIs. The
  old code already used only stable APIs (webview, commands, diff, clipboard).
  The new parts (tree view, status bar, SecretStorage, child process) are
  stable too.
- The `engines.vscode` range must allow the oldest base used by current forks.
  The old `^1.106.0` is probably too new for some forks; check before
  publishing.
- Cursor's Open VSX mirror can lag behind new versions. The README must not
  promise same-day updates there.
