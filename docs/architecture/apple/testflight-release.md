# Apple changes: dev and TestFlight release

Use this procedure for publishing an already implemented Apple change. Reuse the
assigned session, scoped diff and retained build/test evidence. Run additional
checks only for changed inputs, a concrete failure or a required gate. Physical
APNs delivery and real-account cross-device behavior need their own evidence;
an archive or fixture pass does not establish them.

## Prepare once

- Freeze implementation before archive creation. One owner runs Xcode and owns
  the release wait; helpers must finish edits and avoid competing native work.
- Use the selected Xcode through `DEVELOPER_DIR`, Python 3.10 or newer, and the
  existing repository dependency runtime. If workspace PyYAML needs `PYTHONPATH`,
  make it absolute so disposable integration checkouts can also resolve it.
- Reuse an existing ExportOptions plist and signed-in Xcode account. Inspect
  `scripts/apple_testflight_release.py --help` for current options. Choose one
  marketing version and one unused build number for iOS, Watch and macOS.
- Before the expensive archive, check the source iOS/macOS entitlements and
  provisioning capability against the intended relying-party domains and the
  deployed AASA: passkeys need `webcredentials`, app links need `applinks`, and
  the AASA application identifier must match the signing team and bundle ID.
  The helper's validation of actual signed archive entitlements remains required.
- Inspect free disk and active native work. Close only unneeded Xcode/Simulator
  processes belonging to this session. Preserve installed apps, account data,
  unrelated caches and existing test evidence. Outside Simulator, follow the
  user's delivery route; do not substitute a locally launched Debug Mac app.

## Publish the scoped dev changes

Use the normal `scripts/sessions.py deploy` helper and required provenance
trailers. For frontend changes, wait on
`scripts/sessions.py wait-deploy --commit <deployed-sha>`.

If the Mac lacks the deployment credential or the Docker runtime needed to
publish CI candidates, use the user's approved dev-server route. The repository's
Vercel billing guard can also apply to a documentation/skill deploy; do not assume
a non-web diff is exempt. Do not install
Docker or request a new Vercel token just to replace that existing route. On
macOS, an existing key stored in Keychain may require
`ssh -o UseKeychain=yes -o BatchMode=yes <approved-dev-host>`; use the configured
public host when a private alias is unreachable. Keep connection details local.

Reuse the server deployment binding, or create an isolated binding for this
transfer when none exists. Transfer only the owned patch and file inventory,
verify its digest, and check the three-way application before applying it. Publish
an immutable candidate with `sessions.py ci-source --session <binding>`; this
command already emits a JSON receipt and has no `--json` flag. Regenerate
Specification artifacts after editing tests. For a reviewed deployment, derive
the exact `--only` list from the receipt's `changed_paths` and pass
`--reviewed-candidate <source> --reviewed-base <base>` to the normal deploy helper.
Do not bypass lint, billing or test gates.

For Mac-side deployment tooling, use the repository's pinned pnpm version and
an installed Bash supporting the helper's `mapfile` usage. Reuse these tools and
existing dependency caches; fix only a demonstrated missing package/tool.
Fixture-only component CI uses `--mode component`. If the coordinator rejects
component targets in prepared-build mode, its supported `--no-prepared-builds`
cold mode runs the same assertions. Keep passing evidence and rerun only affected
checks. Bare preview tests should use the shared `waitForComponentPreview`
readiness signal before inspecting the mounted component.

## Archive and upload

From the assigned workspace, inspect commands without uploading:

```bash
python3 scripts/apple_testflight_release.py --dry-run --build-number N \
  --export-options .runtime/<existing-release>/ExportOptions.plist
```

Run the same entrypoint without `--dry-run`. It generates translation/token
inputs, validates source-bound receipts, archives iOS with Watch and universal
macOS, then uploads both. On constrained Macs, run it at lower priority, for
example `nice -n 10 python3 ...`, and keep native compilation to one job. The
Mac archive already uses `-jobs 1`; inspect the dry run before adding anything.
When the iOS command lacks a job limit, a repository-local `xcodebuild` wrapper
on `PATH` may add `-jobs 1` only to archive commands without an existing limit.
Delegate to the real selected Xcode binary, preserve all other arguments and
leave export/upload commands intact. Do not change signing to reduce load.

Wait on the running process with bounded waits; read a stage log only for a
changed stage or failure. Do not run a second release or duplicate status monitor.
Keep source inputs frozen until both uploads finish.

After a failure, rerun the same version/build/release directory so completed
stages resume. If source changed, use `--rebuild-stale-archives` to preserve and
replace mismatching archives. Do not reuse a differently signed/source archive,
erase receipts to force acceptance, or re-upload a build already accepted by
Apple. Reassess repeated failures before starting another expensive attempt.

## Verify availability and clean up

With App Store Connect API credentials, the helper waits for both platform builds
to be valid; a later retry may use its printed `--verify-only` command. Without
API credentials, pass an explicit build number and use the signed-in Xcode
account for upload. `uploaded_processing_unverified` confirms accepted uploads,
not availability. Verify the intended version/build in TestFlight for **each
platform**. Use Previous Builds if the main detail page still shows a cached
build. Do not treat a macOS listing as iOS proof or claim a processed API receipt
from a UI check. Confirm the Watch bundle/version in the validated iOS archive;
physical installation and behavior remain separate verification.

After successful uploads, remove only this session's reproducible `ios-derived`
and `mac-derived` caches if cleanup is requested or disk pressure warrants it.
Retain signed archives, release/upload receipts, logs, screenshots and xcresults.
Stop any remaining unneeded native processes from this session. Report dev
commit/deployment status, per-platform TestFlight availability, verified changes
and actual open failures. A release-only request does not start another parity
sweep.
