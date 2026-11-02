The additive `session.ephemeral-metadata-startup.v1` capability is authored and
UNRUN. It is partial in every SDK and cannot be treated as release, physical
persistence, browser, performance or backend-compatibility acceptance.

Rust exposes `client::ephemeral_metadata`; npm/Python expose
`MetadataAuthentication`, `EphemeralMetadataClient`, the prepared startup and
opaque snapshot. The adapters call the native library directly. Supply explicit
`apiUrl`, `appUrl`, `sessionId` and cookie map. There is no owner/User DTO, API-key,
Master, placeholder key, CLI profile, host callback, enrollment or readiness input.
The Rust caller supplies `MetadataEndpointOptions` and
`MetadataCookieCredentials`; npm/Python fix their own native SDK identity.

Explicit authentication cancellation also retires its issued context through the
original negative token. Collecting the pending facade does not cancel a returned
context. Abandoned actual authentication work remains bounded in Rust.

Pending credentials do not contain an authenticated principal or store. Only the
existing real `POST /v1/auth/session` response with success, actual nonempty user
identity and WS token issues the new context. Core then allocates its actual
volatile memory store. Startup reauthenticates the same original source and
principal before opening its own socket. Real cookie headers are merged into the
original holder before body/denial/cancellation checks. Credential snapshots are
explicit caller output; retain/save them with the caller's existing secure policy
even after a failed operation. No implicit storage backend is added.

The socket is passive and never announces an active chat. Core waits for actual
discovery, sends the existing bounded `phased_sync_request`, accepts the original
phased terminal, then requests existing expanded metadata only when the actual
Phase2 server count exceeds 100. It reuses the maintained sync/metadata parser,
including all Phase1 metadata, the 20-parent content budget, sidecar validation,
context correlation and per-operation byte bounds. It retains only opaque
metadata rows/order in its own memory; all remaining window/sidecar data is wiped.
No content decryption, selected read, private publication, durable commit,
native-profile conversion, recovery claim or full/later-hint ACK API exists.
The one public observation is received metadata count against the same context;
it is not an authoritative account total or ongoing-live-session assertion.

Each preparation invalidates prior memory generations. Foreign original stores,
canceled operations and closed contexts cannot release count. Actual principal
changes, server denial, known received cookie Max-Age/deletion expiry and failed
startup retire the original. Endpoints, identity and credential source cannot be
replaced. A new input object requires new real server authentication. The resource
does not monitor an account after its socket closes; unseen later remote
revocation cannot be represented as a positive ongoing auth guarantee. Every new
startup revalidates remotely. Team startup, physical/durable cache integration,
browser/UI activation, app offline queues and canonical-store parity remain open.

HTTP has a 25-second overall deadline and 16-MiB response ceiling; actual observed
headers survive cancellation/failed body completion. Socket handshake is bounded
to 10 seconds, exchange to 30 seconds and original socket close to two seconds.
Close retires immediately and waits at most 35 seconds for the original driver;
timeout is an error, never a global/durable-settlement receipt. Native futures
retain actual bounded work across foreign future abandonment. The binding's
negative cancellation owner transfers to its returned opaque snapshot; dropping
an operation cannot manufacture a new positive resource or ACK.

V3 preserves all original 19 vectors/assertions and appends eight actual HTTP
variants (27 total): a valid rotation followed by an invalid preference or
undecodable header; malformed/truncated/held authentication bodies; cancellation
before headers and after observed headers; and supported foreign-future
cancellation. The same maintained pure cookie-pair parser serves both the Client
and this separate holder. The Client's final atomic validation and guards are
unchanged. The metadata holder now validates/commits each admissible actual
observation before inspecting a later header, retaining real rotation while
refusing the invalid cookie. Its pending input still cannot issue a scope on any
failed/canceled body.

`MetadataAuthentication.cancelAndDrain` / Python `cancel_and_drain` cancel the
original negative token then await only the actually reserved Core auth driver,
bounded to 30 seconds. Rust callers cancel their original token then call
`PreparedMetadataAuthentication.wait_for_authentication_io`. Driver ownership is
reserved before dispatch/spawn. This barrier gives no account, store, scope,
readiness or protocol ACK grant. A held auth body remains explicitly unknown
until actual original IO ends; a foreign canceled future is not evidence of that
event. Rust tests abort the outer future AFTER explicit original cancellation;
Python Task cancellation propagates its supported original negative token. npm
uses explicit original cancellation and never claims that dropping a JS Promise
proves cancellation or drain. Each adapter observes real retained rotation and
asserts no scope delivery, no socket and no rearm; the independent peer checks
exact request/header/body order and completion in addition to original counts.

V4 scans the entire already-received header batch under the original holder
lock. It remembers the first refusal, discards every inadmissible candidate,
continues retaining each later admissible observation and returns the refusal
only after scanning. Thus both valid-then-invalid and invalid-then-valid header
orders retain real auth rotation without committing the invalid cookie or
issuing authenticated scope. Two reverse-order real direct-adapter cases are
appended; all 27 prior vector objects and body/cancel/drain assertions remain.

The shared fixture has 29 actual direct-library vectors and no Master input.
`session-ephemeral-metadata-gate.py` owns each in-process independent peer and
uses the maintained reserved process-group utility for each fixed Rust/npm/Python
adapter. The peer rejects extra routes, messages, ACKs or claim/write commands,
checks real native identity, cookie rotations, same original epoch and terminal
ordering, and requires each owned socket disconnect. The gate requires the exact
fixture bytes and every vector result in order. Pure schema/receipt tests are
supporting checks only. Root must register all three fixed commands in the
protected conformance controller, source pins, plans and matrix before execution.

No existing SessionClient/Master or browser Worker/IndexedDB proof is weakened.
The existing browser selected-metadata 15 cases and startup/monitor vectors remain
literal. A memory-store observation cannot satisfy any canonical native DB,
profile, browser commit/readback or UI rule. The SDK memory capability is a
separate Core-owned runtime resource within the approved auth/crypto separation.
