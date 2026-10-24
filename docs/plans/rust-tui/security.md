# Native Rust TUI security inventory

This is a scoped implementation and evidence inventory, not a claim of complete security equivalence or an independent cryptographic audit. The baseline is the current TypeScript CLI/TUI and shared browser protocols. The native application uses the existing first-party endpoints, automatic AI routing, encrypted wire formats and server authorization; it does not introduce a new public plaintext API.

The reviewed native source is `frontend/packages/openmates-tui-native`. Dependency results are recorded in [dependency-audit.json](dependency-audit.json), tied to the exact `Cargo.lock` SHA-256. Product protocol and real-terminal evidence belongs in the final [report](report.md); unit fixtures do not establish server or operating-system integration by themselves.

## Controls and evidence

| Boundary | Existing TypeScript control | Native implementation and evidence | Qualification |
|---|---|---|---|
| Password sign-in | Hashed email lookup, versioned password proof, optional TOTP, client-side master-key unwrap | `client/auth.rs` and `crypto.rs`: Argon2id 64 MiB / three iterations / one lane, separate HKDF auth/wrap keys, purpose-bound HMAC proof, existing PBKDF2 v1 compatibility. `tests/crypto_interop.rs` verifies shared auth/wrap/proof vectors and both master-key wrapper versions. | Full login/TOTP/cookie behavior requires the isolated `protocol_smoke` fixture; crypto vectors alone do not prove endpoint compatibility. Native v1 fallback depends on the server's existing downgrade restriction. |
| Pair sign-in | OPAQUE v2, canonical context, receiver capability, verified grant, persist before acknowledgement | `pairing.rs`, `client/pair.rs`, `runtime.rs`: pinned `opaque-ke` 4.0.0 Ristretto255 / TripleDH-SHA512 and canonical Argon2 KSF, context-bound identifiers and AES-GCM AAD, strict capability encoding, one-use PAKE state. Static published-JavaScript 1.1.0 transcript verifies the exact native final proof and bundle decryption; tests reject wrong PIN/context, replay, altered ciphertext/IV, extra bundle fields and invalid grants. Runtime saves before relay acknowledgement. | Static synthetic interop does not replace an isolated browser-to-native pairing lifecycle test. Direct-recipient envelopes are exercised separately by native recipient-binding tests. |
| Transport and session | Protected first-party cookies, refresh ordering, logout/expiry handling, request scope | `client/transport.rs` restricts API authority, requires HTTPS except literal loopback, rejects redirects, validates cookie bytes, bounds HTTP bodies and WebSocket frames, and serializes cookie rotation through mutable `Client`. `Client::forget_session` clears account caches; runtime security/view epochs discard late UI updates. Transport unit tests cover hostile origins, URL authority replacement, cookie injection and redirects. | Browser cookie policy is not reused: as with the CLI, the native cookie jar stores name/value pairs. Real refresh and force-logout races still need product protocol evidence. |
| Encrypted wire data and recovery | AES-256-GCM combined ciphertext, per-object keys, HKDF embed/recovery keys, identity-bound recovery | `crypto.rs` preserves IV/ciphertext/tag layout. Decryption first tries a valid browser OM/FNV-framed candidate, then authenticates the entire legacy buffer with AES-GCM: a random legacy IV may itself begin with `OM`. Neither path accepts unauthenticated plaintext; canonical writes are unchanged. Recovery uses contributory X25519, HKDF-SHA256, canonical UUID/version AAD and authenticated envelope validation. Shared backend/CLI/browser recovery vectors and independent Python AES/PBKDF2/HKDF fixtures cover wrong keys, tampering, substituted identities and low-order public keys. | Fingerprints detect a wrong key; AES-GCM supplies authentication. Native OMCR2 typed-output replay additionally binds identities, verifies canonical ciphertext/digests and acknowledges exact versions. Shared backend golden fixtures and malformed/revision tests cover this path; live inference/recovery remains unverified. |
| Persistent credentials and cache | OS keyring when available; owner-only file and legacy storage modes also exist in the CLI | `storage.rs` uses an independent native profile. Session contents are authenticated ciphertext, with an OS-keyring secret, a random owner-only local wrapping-key file on first-write keyring unavailability, or an explicit passphrase vault; an existing keyring failure does not downgrade storage. Cache AAD binds account, profile/session and cache context. Private directory/file modes, no-follow descriptor traversal, hardlink rejection, atomic replacement, lifetime/process locks and retryable deletion markers are exercised by `tests/storage_security.rs`. `runtime_store.rs` keeps blocking operations ordered even when a waiting future is cancelled. | Restricted local-file mode has owner-only filesystem protection and is not described as keyring-equivalent. It preserves login without requiring another password; explicit vault mode remains available. The native store intentionally does not read or rewrite legacy CLI credential files. Fake keyring tests establish failure behavior, not successful access to a real desktop keyring. Supported filesystem evidence is Unix; no Windows security equivalence is claimed. |
| Owner and Team isolation | Owner/Team query scope, wrapped group/object keys, explicit context switches | `client/sync.rs`, `workspaces.rs` and `team.rs` select scoped key wrappers, reject Team-to-Personal fallback and reject group-key fallback for direct chats. Existing direct identity backups are verified against their X25519 key pair and key ID; OMDM1 recipient envelopes bind Team, chat and recipient. Switching context clears ciphertext/key caches and advances generation; cache context includes Personal versus Team identity. Unit tests cover wrapper scope, recipient-envelope identity, preview consent, fresh membership and idle revocation. | Native ordinary Team messages send ciphertext only; explicit AI mentions use fresh Team-only context. Direct history requires online identity recovery after restart because the backup is not yet persisted locally. Actual server owner/membership enforcement needs isolated multi-account evidence. |
| Project Task hook cache | Explicit owner-private plaintext cache compatible with local Codex readers | Application-owned `project_task_cache.rs` writes plaintext titles, bounded descriptions/activity and ownership metadata to `snapshot.json` and derived `tasks.txt`, with `0700` directories, `0600` files, descriptor-anchored no-follow operations, hardlink rejection, writer locking and atomic publication. Recovery authenticates encrypted Task records through the headless SDK before restoring readable content; reconnect/revocation markers fence hook readiness. | This cache is separate from encrypted credential/chat storage and is not encrypted by the credential vault. Filesystem privacy does not protect against the owning user, privileged processes, backups or forensic recovery. This foundation does not establish foreground network integration or a whole remote-access implementation. |
| Chat/message privacy | Ordered deterministic detection, configured personal-data memories, reversible encrypted mappings, current send context | `privacy.rs` ports all 31 current pattern entries, category/master settings, Luhn/IBAN/phone/system-account validation, URL/coding-identifier shields, personal data/address lines, stable existing mappings and one-pass restoration. Shared-source fixtures exercise 38 synthetic cases. `client/send.rs` obtains and validates a same-socket Personal context snapshot before admission; original mappings are encrypted with the chat key. Missing/conflicting generated mappings fail closed on restoration. | These are deterministic supported patterns, not universal PII recognition. User-disabled categories remain disabled. Decrypted memory consent uses a separate explicit request-bound UI decision; no automatic consent is implied. |
| Explicit Apps execution | Confirmed typed provider input, current availability/schema, encrypted result index and owner checks | `client/apps.rs` fetches canonical public form metadata, validates the selected request, requires Personal scope, preserves automatic routing and blocks unsupported enhanced privacy. Like `executeConfirmedTuiAppsSkill`, the typed request is sent directly to its selected skill after explicit UI confirmation; private memories are not included implicitly. Pending/results are encrypted under a random key wrapped by the account master key. Accepted task IDs are retained before polling; cancellation does not replay a billable POST or invent a task-cancellation API. Mock unit tests cover sync/async results, encrypted retention, cancellation and redacted failures. | This is not natural-language Apps interpretation or an anonymization pass over provider parameters: that would change an explicitly confirmed query/location/capability. The native natural-language interpreter, generic sandbox execution streaming and full Apps library/history UI are separate parity work. Sandbox-mode skills are explicitly unavailable in this form; other direct results are returned as actual structured content. Local mocks establish request construction, not live billing/provider/server compatibility. |
| Enhanced semantic privacy | Optional local model, explicitly enabled profile preferences | `verify_enhanced_disabled` safely validates the existing profile preference file and explicitly blocks submission when enhanced mode is enabled. Preference tests cover malformed state, unsafe modes and symlinks. | The Rust application currently has no semantic model implementation. It does not launch the JavaScript privacy daemon or silently substitute deterministic-only detection for an opted-in enhanced mode. |
| Share links | AES-GCM/PBKDF2 key blob in URL fragment, optional password, share-PII flag | `client/actions.rs` uses canonical salts, 100,000 PBKDF2-SHA256 iterations, field serialization, supported expiration values and ten UTF-16-unit password limit. Only share metadata and the explicit `share_pii` flag go in HTTP; chat key material stays in the encrypted fragment. Unit tests decrypt both ordinary/password blobs and verify fields. | The existing share-link possession/password threat model is preserved. Browser recipient interoperability and server metadata authorization still require isolated protocol evidence. |
| Downloads | Explicit destination and overwrite consent; full-history export | `client/actions.rs` requires complete live chat pagination for Markdown, and resolves selected Project source from project-scoped embed ciphertext and native JSON/TOON decoding. Output uses pinned directory descriptors, private temporary files, atomic/no-clobber publication, owned regular-file checks, no symlinks/hardlinks, and destination identity/size/mtime revalidation. Action tests cover actual source extraction, private modes, changed targets and hostile links. | Source is exported only through an explicit user action. Secure file export is currently Unix-only; other platforms fail explicitly. Unit tests do not prove all hosted/upload embed formats. |
| Terminal and UI | No execution of content-provided terminal sequences; explicit link/clipboard actions | `ui/markdown.rs` and `ui/editor.rs` filter terminal control bytes. Link opening accepts HTTP(S), rejects URL credentials and requires an explicit UI action; clipboard copy is explicit. Secret forms are masked and use zeroizing secret editor buffers. Unit tests cover control-byte filtering, Unicode editing/masking and private-view clearing. | Explicit exported/copied source can contain private data by design. No guarantee is made against a hostile terminal emulator, screen capture or an already compromised OS. |
| Cancellation and shutdown | Cancel active inference, discard stale work and restore terminal state | `client/send.rs` binds streaming/recovery events to chat/user-turn identity, sends best-effort task cancellation, and waits for encrypted admission/persistence acknowledgements. `runtime.rs` uses generation fences, priority security transitions, a terminal guard and a redacted panic hook. `runtime_store` tests ensure logout cannot overtake a started cancelled save. | Signal restoration and real-terminal lifecycle need the final CI evidence. Process kill/abort and an uncooperative OS cannot guarantee cleanup or cancellation delivery. |

## Logout and explicit credential state

Local logout announces a durable revocation epoch through a separate descriptor-bound
filesystem worker before queued keyring cleanup. The terminal priority lane makes
that announcement even while the SDK actor is awaiting a native keyring call.
Canceled error-path persistence has a bounded grace period; started writes retain
their ordering permit and recheck the revocation epoch before publication. Fresh
password/pair admission must explicitly authorize its new session context; boot,
cookie rotation and ordinary persistence cannot reopen a revoked context. The
small nonsecret `revocation.json` marker survives successful cleanup to prevent
restart resurrection. Native keyring cleanup and remote logout remain separately
fallible; a local fence is not proof of server revocation.

Explicit API keys use a hashed per-origin/per-bearer child state for device approval
and delivery journals, independently of cookie-profile login and its lifetime lock.
They do not unlock the cookie vault, discover its credentials, or reset its logout
fence. Focused profile tests exercise operation while the cookie profile is locked
and revoked. A cookie-based CLI command and an open TUI still cannot share the same
exclusive profile; resolving that transition gap must preserve durable credential
ordering rather than weakening the lock.

## Volatile chat boundaries

Authenticated incognito and the explicit public anonymous API use volatile send paths. They suppress durable Task jobs, saved context, drafts, recovery admissions and ciphertext-cache insertion; ephemeral IDs are rejected by saved-chat operations. Anonymous HTTP carries no Cookie, bearer, Origin or account-device headers, even when the SDK client holds an explicit session. The application owns a separate UUID in a private per-origin anonymous child profile; it is not an authentication credential or a transcript and survives logout. File tests reject malformed IDs, symlinks and hardlinks. Shared protocol fixtures cover header isolation, cancellation and PII restoration; real inference and volatile history continuation remain separate evidence gaps.

## Dependency audit

**Latest check, 2026-10-24: blocked.** All four current lockfiles fail on
`crypto-bigint 0.5.5`, affected by
[RUSTSEC-2026-0387](https://github.com/RustSec/advisory-db/blob/21d909e4c8bd4e14c7aea58bf980c881a0053ab1/crates/crypto-bigint/RUSTSEC-2026-0387.md).
The advisory concerns timing variability in operations intended to be constant
time and lists `>=0.7.6` as patched. The fresh, clean RustSec database is commit
`21d909e4c8bd4e14c7aea58bf980c881a0053ab1`; all four lock hashes remain unchanged
through the scan. No ignores, target filters or warning suppression were used.
The native keyring chain also retains the three maintenance notices below.
The [existing audit record](dependency-audit.json) preserves this follow-up beside
the historical checks. Native SDK tests passing does not clear this finding.
Dependency-chain remediation and actual Ristretto-path reachability review remain
open; lockfile presence alone does not establish practical exploitability. New
installation and release acceptance remain held pending resolution and checks.

The audit evaluates the committed native lockfile against a fetched RustSec database, with no advisory ignores and no target filters. Vulnerabilities fail the audit by default; unsound and yanked dependencies are also denied. Unmaintained notices are reported separately, because RustSec distinguishes maintenance notices from a demonstrated vulnerability. See the [RustSec advisory format](https://github.com/RustSec/advisory-db) and [cargo-audit documentation](https://github.com/rustsec/rustsec/blob/main/cargo-audit/README.md).

Audit results and the reproducible command are recorded in `dependency-audit.json`. A clean lockfile scan means no matching published advisory was found in that database snapshot. It does not establish the absence of vulnerabilities, audit the application's protocol logic, assess every enabled feature's reachability, verify build provenance, or provide a license review. Cross-platform and build-only packages in the lockfile remain visible to the scan.

The 2026-10-22 follow-up uses cargo-audit 0.22.2 and clean RustSec commit
`640bf5a9f06e66d8721e8772766531fe77c8630d` (1,349 advisories), held unchanged
across all three scans. Native, SDK and binding lockfiles contain 428, 227 and
247 packages respectively; each passes with **zero known vulnerabilities, zero
unsound warnings and zero yanked warnings**. Exact lock hashes and raw reports
are retained in the canonical audit JSON.

The fresh database first rejected existing Tokio 1.54.0 for
[RUSTSEC-2026-0384](https://github.com/RustSec/advisory-db/blob/640bf5a9f06e66d8721e8772766531fe77c8630d/crates/tokio/RUSTSEC-2026-0384.md),
a multithreaded `Interval` timer race/use-after-free. All three manifests now pin
patched 1.54.1; the patch changes only Tokio in each lockfile, separately from
six new ICU collation dependency packages. No advisory ignore or platform filter
was added. The earlier passing snapshot and rejected follow-up are preserved.
Source `2d94b407` and its pinned binary still contain the affected older version;
functional CI from that source cannot authorize installation or publication.

Three maintenance notices remain in the Linux Secret Service keyring dependency chain (`keyring` 3.6.3 → `zbus` 4.4.0, also through `secret-service` 4.0.0):

| Package | Notice | Disposition |
|---|---|---|
| `zvariant` 4.2.0 | [RUSTSEC-2026-0370](https://rustsec.org/advisories/RUSTSEC-2026-0370.html) | Maintenance follow-up; upstream functionality moved into `zbus` 6. |
| `zbus_names` 3.0.0 | [RUSTSEC-2026-0371](https://rustsec.org/advisories/RUSTSEC-2026-0371.html) | Maintenance follow-up; same upstream migration. |
| `zvariant_derive` 4.2.0 | [RUSTSEC-2026-0372](https://rustsec.org/advisories/RUSTSEC-2026-0372.html) | Build-time derive dependency; same upstream migration. |

These are reported, unsuppressed informational notices, not a demonstrated vulnerability in this scan. No broad keyring/D-Bus upgrade was made as part of this audit. Moving the dependency chain to maintained upstream packages requires its own compatibility verification; the absence of a vulnerability finding does not remove that maintenance work.

## Remaining evidence and restrictions

1. Do not replace the installed TypeScript TUI on the basis of unit vectors or a clean dependency scan alone. The accepted plan still requires isolated product protocol, real-terminal, owner/Team and cancellation evidence, plus the feature inventory in the final report.
2. Project/remote execution jobs, countdown/connected-account approvals, enhanced semantic privacy, direct identity recovery across offline restarts and non-Unix secure downloads remain restrictions or missing branches. They are not silently routed through TypeScript or a sidecar.
3. Keys, password-derived material, PAKE state and Argon2 memory matrices use explicit zeroization where owned by the native implementation. Ordinary decrypted UI strings, privacy mappings, parser allocations, library internals, OS clipboard/browser memory, swap and crash dumps are not covered by a claim of exhaustive RAM erasure.
4. Re-run the audit after any `Cargo.lock` change or before a later release. The JSON records the database commit and lockfile digest so stale evidence is identifiable.
