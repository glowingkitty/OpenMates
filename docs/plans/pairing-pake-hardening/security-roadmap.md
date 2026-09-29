# Agreed authentication and key-security work

This records the decisions made during the September 2026 security review. It is
an implementation sequence, not a claim that the existing code already meets
every requirement. The current implementation Task is the PAKE pairing change in
`plan.yml`. The remaining work needs separate implementation and verification.

## Invariants

- A fresh supported device can log in with the ordinary password, supported
  passkey PRF, or recovery key and locally unwrap the existing master key. Other
  devices need not be online. No separate encryption password is added.
- Email verification alone cannot recover the existing encryption key or history.
- Authentication authority is separate from content-decryption authority. A
  server-visible credential must not also be sufficient to unwrap the account key.
- A logical session survives token rotation with its own security state; a
  targeted expiry, challenge, or logout does not affect sibling sessions.
- Sharing-password changes are out of scope. No historical master-key rotation
  or destructive data migration is authorized by this pairing Task.

## Implementation sequence and verification

| Work | Architecture and code | Required evidence | Visible effect |
| --- | --- | --- | --- |
| PAKE pairing, implementing now | Client-only PIN and ephemeral OPAQUE registration; API relays messages; confirmed channel transfers master key and random single-use grant. Shared `pairing-crypto`, web pairing components, CLI client, Apple bridge/runtime, `auth_pair_v2.py`. Durable pending-ack session and absolute deadline in backend. | Wrong PIN/context/tamper/replay/cancel rejection, atomic grant consumption, save-before-ack, JS/native interoperability, real web/CLI encrypted draft restoration, web receiver, expiry after refresh/cache loss, sibling isolation. | Same approve/display-PIN/enter-PIN interaction. Approver stays open. Old pairing clients must update. Native settings starts approval of the new device's code rather than displaying a receiver code on the already signed-in device. |
| Verified login and sensitive actions | Replace untyped method selection with typed credential records and verified, purpose-bound authentication results in `auth_login.py`, `auth_passkey.py`, recovery routes, and schemas. Add a shared server guard for settings credential/factor/API-key/contact mutations. Remove internal-marker trust from `auth_ws.py`. | Method substitution and forged internal marker rejected; second-factor errors fail closed; direct mutation API calls without assurance rejected; same-session proof at two minutes accepted and stale/other-session proof rejected. | Reuse strong authentication from the same logical session for five minutes. Existing verification dialogs remain; an action needs a prompt only when no adequate recent proof exists. |
| Authoritative sessions and credentials | Make durable logical-session state authoritative in auth dependencies, issuer refresh, session revoke, WS handshake/live connections, and API-key authentication. Transactionally replace typed credentials and wrappers; invalidate old factor/key caches. | Revocation with warm/cold caches and issuer refresh; old password/recovery key rejection after rotation; expired API key rejection; concurrent backup-code/OTP/challenge replay; injected replacement failures preserve usable state. | Expired/revoked sessions actually stop working. No new ordinary login steps. |
| SDK key separation and migration | Version SDK provisioning in `SettingsApiKeys.svelte`, API-key/settings routes, SDK bootstrap, and npm/pip clients. Parse independent authentication and client-only decryption components locally; send only authentication material. Limited integrations receive only permitted resource-key grants, not the account master key. Reject old key formats after an explicit cutoff. | Backend-visible bearer plus stored wrapper cannot decrypt a synthetic root; limited grant cannot decrypt unrelated resource ciphertext; expired/revoked keys fail even with a warm cache; mixed-version downgrade rejected. | Upgrade to a minimum safe SDK version and replace legacy API keys/configuration. A single setup value can remain, but raw HTTP callers must send only its authentication component. Revoking CLI cookie sessions does not revoke SDK API keys. |
| Password protection, signup, and recovery | Version password authentication and master-key wrapping together, benchmark memory-hard parameters, and migrate on successful local unlock without retaining a fast verifier. Bind email proof to a client-held signup transaction and verify passkey registration before account commit. Implement staged, idempotent destructive recovery with a 24-hour cancellable delay and authoritative revocation. | Fresh-device unlock preserves history; interrupted migration remains usable; cross-transaction email proof rejected; invalid passkey creates no account; cancellation prevents deletion; reset failure/retry cannot claim partial success. | Ordinary login fields unchanged. Email-only destructive reset has the explicitly approved 24-hour delay, notification, cancellation, and progress/failure states. |
| Local storage and secret lifecycle | Refactor CLI `keychain.ts`/`storage.ts` to prefer a working OS keyring, otherwise use a clearly identified permission-restricted local credential file. Keep legacy machine-key decoding only as needed for safe migration; do not label machine identifiers as secret protection. Await browser/Apple/CLI cleanup; redact auth validation/logging; remove redundant refresh JSON/query transport. Finish durable media-key wrapping in upload/music writers and readers separately. | Keyring present/absent/locked tests, file/directory permissions and safe atomic writes, migration/readback and cleanup failure tests; synthetic secret markers absent from logs; durable media records contain validated wrappers without redundant raw keys. | No mandatory `secret-tool`, new setup command, automatic OS package installation, or new encryption password. Show the actual storage mode. Headless Linux remains supported with host-protected files. Cleanup failures are truthful. |

## CLI storage decision

Use a functioning OS keyring opportunistically. Otherwise the supported ordinary
headless path is a local credential file readable only by its owner (0600) inside
an owner-only directory (0700). Make the selected protection mode visible without
an extra confirmation ceremony. Never silently switch an existing keyring-backed
session to a weaker mode because retrieval failed; an unavailable/locked existing
entry is a distinct error from first-time fallback selection.

The file can contain chat decryption material as well as service credentials, so
this mode trusts the host and account permissions. Machine-ID-derived encryption
does not provide an independent secret against a copied machine image. There is
no mandatory Secret Service daemon and no npm-triggered installation of system
services. The current dev host can use the file mode. This policy is recorded in
the CLI Specification and implemented in the authentication hardening workstream;
final CLI build and isolated integration checks remain pending.

## Cutover

Deploy only after all participating web/CLI/Apple pairing clients speak v2 and
the relay, grants, and deadline checks pass. Disable legacy pairing without a
downgrade path. Define and display the minimum safe CLI version when the release
is actually published; do not hardcode an unpublished version or require an
unrelated newest version forever.

The broader credential migration must invalidate identified legacy CLI sessions
at the authoritative issuer/session layer and require upgrade plus fresh login.
SDK API keys are a separate credential class and need revocation/reissue.
Revocation prevents future authorized access but cannot erase a master key or
plaintext previously copied. Historical exposure and any root/content-key
rotation require a separate evidence-based decision; they are not automatic
consequences of this rollout.

## Specification and tests

`feature.auth` owns account unlock, verified methods, sensitive-action assurance,
pairing, session enforcement, credential transactions, signup, recovery, and
secret lifecycle. `surface.cli` owns storage-mode and CLI upgrade semantics;
`surface.sdk` owns credential separation, limited decryption grants, and key
migration. Their changed assertions have concrete user-readable examples.
These draft changes invalidate prior evidence for the affected assertions;
validation is not proof of implementation. Local unit checks and isolated GitHub
product tests must establish each implemented contract before it is reported as
complete. A dedicated media-key storage contract is deferred to that workstream
instead of adding unrelated product semantics to the account-access bundle.
