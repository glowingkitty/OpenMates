> Deployment status: the final recovery candidate described here remains undeployed after two failed integration cases. This publication only fixes metadata-only inspiration previews and documents the reviewed design. Earlier deployed timing measurements and staged fixes are identified separately in the validation document.

# Prepared privacy and independent chat completion

This describes the reviewed processing design. The latest user direction accepts observed timings and prioritizes completed answers with no request-related client or backend errors. The diagrams describe implementation and do not certify deployment or a passing run; scenario results, raw errors, and historical timing checkpoints live in [validation-2026-10-15.md](validation-2026-10-15.md).

## Processing flow

```mermaid
flowchart TD
  Open[Composer focus / microphone / authenticated TUI startup] --> Warm[Prepare chat identity and key; authenticated connection; encrypted discovery]
  Open --> Privacy[Fetch consistent Personal privacy snapshot and generation; decrypt and compile locally]
  Send[Send: show one user row and clear submitted composer] --> Fresh[Fresh authority and privacy generation validation]
  Privacy --> Fresh
  Fresh --> Reuse{Prepared generation and scope match?}
  Reuse -- yes --> Ready[Reuse local privacy options and obtain one-use turn receipt]
  Reuse -- no / unsupported --> Full[Fetch complete fresh snapshot; decrypt and compile locally]
  Full --> Ready
  Warm --> Envelope[Independent key and encrypted recovery preparation]
  Ready --> Filter[Apply configured local privacy filtering]
  Filter --> Admit[One admission: transient processing text plus encrypted durable message]
  Envelope --> Admit
  Admit --> Durable[Consume receipt; authoritative access/budget checks and durable idempotent admission]
  Durable --> J1[Jev stage 1: compact routing]
  J1 --> Resolve[Resolve actual permitted model and Mate]
  Resolve --> Feedback[Publish selected Mate; client displays localized Thinking]
  Resolve --> Need{Detailed context or capabilities needed?}
  Need -- yes / uncertain --> J2[Jev stage 2: detailed selection]
  J2 --> Consent{Project or Focus activation required?}
  Consent -- yes --> Activate[Existing consent or cancellable countdown; fresh authority]
  Activate --> Hydrate[Authorize and load selected context concurrently]
  Consent -- no --> Hydrate
  Need -- complete empty context --> Main[Main: required instructions and relevant conversation]
  Hydrate --> Main
  Main --> Stream[Stream authored text and ordered skill events]
  Stream --> Terminal[Authoritative response terminal: stop active label and glow]
  Terminal --> Persist[Required encrypted reply persistence: next Send ready]
  Terminal --> Post[Independent postprocessing]
  Post --> Metadata[Later header title/summary and follow-up chips update and persist]
```

Composer or microphone focus prepares identity, encrypted discovery, keys and a scoped privacy snapshot without sending draft text or starting inference. Send places one optimistic user row and clears only the submitted composer. Fresh authority, privacy generation, access and spending checks precede durable admission. The existing paired processing text and encrypted durable message do not make plaintext durable. Jev routing selects the Mate before detailed context work; the client can show Thinking while selected resources load. Only the authoritative terminal event ends the active response presentation. Required encrypted reply and output persistence controls the next Send. Header metadata and follow-up suggestions can arrive later through owned, versioned delivery.

## Client preparation and foreground state

```mermaid
flowchart LR
  Start[TUI opens] --> Cached[Render encrypted local cached work]
  Start --> Auth[One serialized current-owner session validation]
  Auth -- valid --> Rotated[Persist current credentials]
  Rotated --> Fanout[Parallel warm-up, activity and workspace discovery]
  Auth -- temporary outage --> Offline[Retain cached work and retry admission]
  Auth -- invalid --> Ended[End expired session]
  Auth -- risk reauthentication --> Reauth[Require reauthentication before remote fanout]
```

The TUI renders locally cached encrypted work independently of session validation. Current account, session and Team credentials are serialized and refreshed before remote fanout; rotated cookies are stored first. Invalid credentials end the session, temporary outages preserve cached work, and risk reauthentication remains separate. The current turn prepares bounded saved history, key wrappers and recovery receipts; unrelated account recovery does not block Send. Foreground presence is per live connection and suppresses email and push only while a real web tab or interactive TUI is present, with delivery rechecking presence. Warm-up performs no inference and carries no draft text.

## Preprocessor wrapper input

```mermaid
flowchart LR
  IDs[Authenticated user / device / Team; chat / turn / message / recovery identities] --> Pre[Preprocessor wrapper]
  Text[Privacy-filtered current message; bounded relevant history / summary; content-free skill ledger] --> Pre
  Active[Fresh active Project / Focus; accepted Task / Plan references; explicit overrides] --> Pre
  Discovery[Authorized Project candidates; Memory keys; connected-account and Workflow discovery] --> Pre
  Config[Public Mate / app catalogue; model preferences; safety, consent and fresh credit policy] --> Pre
  Pre --> First[Compact first-stage decision and permitted model resolution]
  Pre --> Details[Conditional detailed selection and authorized context preparation]
```

The authenticated wrapper binds user, device, Team, chat, turn, message and recovery identities. It receives locally privacy-filtered current text, bounded relevant history or summary, and a content-free skill ledger; active Project or Focus and accepted Task or Plan references; authorized discovery metadata; and public catalog, safety, consent and fresh credit policy. Client privacy configuration is not forwarded wholesale. Discovery data is not permission: selected private bodies require a fresh owner/Team, source-revision and consent check.

## Jev stage 1

```mermaid
flowchart LR
  Conversation[Current request; bounded relevant conversation / summary] --> J1[Jev stage 1]
  Public[Compact Mate choices and app capability descriptions] --> J1
  Routing[Authorized Project routing metadata; explicit routing intent; prior topic / skill ledger] --> J1
  J1 --> Decision[Complexity; Mate; relevant apps / Projects; public safety / language and need decisions]
  Decision --> Model[Chat exact selection / tier preference / configured default model resolution]
  Model --> Mate[Selected-Mate feedback before stage 2]
```

Stage one sees the current request, bounded context, public Mate and app descriptions, and authorized routing metadata. It chooses complexity, Mate and relevant capabilities, then resolves the actual configured model through exact chat selection, tier preference and default routing. Selected-Mate feedback precedes stage two. It does not receive unrelated private bodies or full tool schemas. Detailed selection may be skipped only when authoritative context is complete; message length or a question word alone cannot justify omission.

## Jev stage 2 and selected Project catalog

```mermaid
flowchart LR
  First[Validated stage-one decisions and selected apps] --> Missing{Selected Project catalog missing?}
  Missing -- yes --> Owner[Current owner client returns bounded selected-Project Focus metadata]
  Owner --> J2[Jev stage 2 when needed]
  Missing -- no --> J2
  Skills[Relevant skill IDs and routing hints; Focus definitions; public app Memory guides] --> J2
  User[Authorized Memory / Workflow discovery and Project Focus catalogue] --> J2
  Active[Required active / explicit context; related Task / Plan / recent-work metadata with provenance] --> J2
  J2 --> Selected[Selected skill / Focus / Memory / Workflow / related-work IDs and revisions]
  Selected --> Bodies[Fresh authorization then independent selected-resource reads / decryption]
```

Stage two uses selected skill IDs, Focus definitions, public app Memory guides, authorized Memory/Workflow discovery, Project Focus catalog metadata, and related Task/Plan provenance. If the selected Project catalog is missing, the current owner client returns bounded metadata over its authenticated live socket; an empty catalog and unavailable catalog are distinct outcomes. The response contains no file bodies or full Focus instructions and grants no access. Account, session, Team, chat, socket, turn and offered-Project checks fence the reply; the backend revalidates current owner, source turn and Project access before resuming. Selected-resource bodies are then independently loaded only after their identities and authority are known. Explicit permission to read with a prohibition on edits may enter the read flow; refusal to read, access or use files prevents implicit activation.

## Main model request

```mermaid
flowchart LR
  Required[Complete ethics and mandatory privacy; Mate / identity / language; required answer and composer metadata instructions] --> Main[Configured answer model]
  Context[Current filtered message; history needed for references; relevant summary / attachments] --> Main
  Capabilities[Actual forwarded tool schemas; selected Focus / app guidance; required interaction / format instructions] --> Main
  Bodies[Authorized selected Memory / Workflow / Project context and related references] --> Main
  Cycle[Current tool results; safe-boundary steering; recovery-bound context] --> Main
  Policy[Resolved model / provider / known region / unchanged thinking policy] --> Main
  Main --> Output[Authored chunks; supported visible thinking; chronological tool events]
  Main --> Ghost[Optional trailing contextual composer suggestion, extracted before answer display / storage]
```

The main request retains complete ethics and mandatory privacy instructions, Mate identity, language, answer and composer-metadata requirements, the filtered request, referential history, relevant summary and attachments, actual forwarded tool schemas, selected Focus/app guidance, authorized selected bodies, and current tool results or safe-boundary steering. Missing required ethics or privacy sections trigger a reload and then fail closed. Unused tool or format guidance may be omitted only when complete response requirements justify it; initial facts and contextual follow-ups obey the same rule. OpenMates keeps its existing automatic routing and configured Gemini default with no model, provider or thinking override. The model can emit authored chunks, supported visible thinking and chronological tool events; a trailing contextual composer suggestion is extracted before answer display or storage.

## Postprocessor and delivery

```mermaid
flowchart LR
  User[User request and relevant preceding conversation] --> Post[Postprocessor]
  Final[Final authored assistant answer] --> Post
  Existing[Existing title / summary / tags / language and response settings] --> Post
  Apps[Available app metadata] --> Post
  Post --> Header[Title / summary / tags and permitted metadata]
  Post --> Chips[Follow-up request chips and new-chat suggestions]
  Header --> Delivery[Turn-identified late delivery; version / account / Team / chat fences]
  Chips --> Delivery
```

Postprocessing receives the user request, relevant preceding conversation, final authored answer, existing title/summary/tags/language settings and available app metadata. It produces permitted title, summary and tags plus follow-up chips or new-chat suggestions. The main-generated composer suggestion is separate from these chips. Terminal completion stops the active label and glow; the next Send still waits for required encrypted persistence. Later title/summary versions can update the header, while chips and composer suggestions stay bound to their source turn. A stale optional suggestion write returns a source-correlated not-stored result, while malformed source, access, key and storage failures remain errors. Late metadata cannot revive a terminal response or overwrite a newer turn.

## Cache and authority boundaries

| Data | Retention | Boundary that remains fresh |
| --- | --- | --- |
| Shipped Mate, app, skill, Focus and Memory definitions | Process cache by deployment or configuration revision | Validate required instruction sections; reload invalid bundles |
| Encrypted owner/Team discovery | Scoped Dragonfly cache, two sliding hours | Mutation generation, source revisions and selected-resource access |
| Personal privacy source and compiled options | Device RAM, at most two sliding hours | Durable aggregate generation and session, device and scope on each Send |
| Selected private context | Authorized transient transport and consent-bound retention | Exact owner/Team, source revision and turn authority |
| Access, consent, spending and execution permission | Checked at required boundaries | Never a two-hour positive permission or balance cache |
| Late answer metadata | Client-encrypted storage and bounded delivery | Exact source turn, metadata version and account/chat/Team |

## Shared result recovery

```mermaid
flowchart LR
  Results[Safety-checked skill results] --> Prepare[Prepare ordered children and parent]
  Prepare --> Classify[Fresh Project classification and recovery pin]
  Classify --> Probe[Bounded lookup of existing sealed receipts]
  Probe --> Seal[Seal absent records with current recovery public key]
  Seal --> Commit[Bounded atomic inline write transactions]
  Commit --> Children[Cache and publish children in source order]
  Children --> Parent[Cache and publish parent]
  Parent --> Continue[Model continuation and client rendering]
```

The shared composite lifecycle prepares ordered children and parent, performs fresh grouped Project classification, probes existing sealed receipts, seals absent records, and commits bounded inline transactions before publishing finished cache entries or events. Each transaction accepts at most 32 outputs and 512 KiB; each inline envelope stays at most 256 KiB. A failed transaction rolls back its entries while earlier committed chunks remain recoverable. Registered producers, volatile output, version diffs and large regional-S3 outputs keep their separate lifecycle. Every path retains owner/Team, preflight, deletion, identity, key and commitment checks. A durable ACK follows verified canonical storage and successful required local handling; a queued old discovery page may skip only an identical acknowledged output. Changed identity, failed ACK or local handling, unknown output and new session remain eligible for recovery. The reviewed implementation includes the CMS recovery and embed-version transaction changes. Exact publication, runtime activation and captured results are recorded separately in the validation document; the diagram alone does not prove deployment or a measured speedup.
## Turn authority and client lifecycle

A Focus activation pauses the admitted user turn. Its internal answer execution has a distinct execution ID but retains the authenticated ROOT chat and source-turn authority through a trusted server mapping. Completion, Stop and failure release or hand off only that ROOT; they cannot erase a newer owner or accepted queued followers. A pending pause has a generation-specific 35-second watchdog that cannot expire a running child or later pause. A matching `already_started` queue result is handled within the same admitted turn rather than granting a new authority. Recent-work reads and writes still require owner, active-task, source-turn and completion-permit checks.

The web sender uses the latest acknowledged canonical message version after the active-turn barrier settles. A saved follow-up remains an existing-chat request even if the local optimistic counter is stale; fresh saved history, privacy generation, immutable retry transport and backend metadata checks still apply. Batched history encryption validates every row before replacing cached history and preserves chronological and empty-string semantics. A missing or unreadable history never becomes an empty conversation.

Completion conflict recovery reads the authoritative version through the existing archive-aware fetch wrapper, including its required storage capability header. It preserves owner/Team scope, credentials, the five-second transport budget and strict chat/revision validation. A denied or failed refresh keeps the original completion conflict visible; it cannot manufacture a replacement version.

Active-chat header and message-window refreshes recheck selection after every awaited read. ChatHistory's delayed new-user scroll keeps its original connected container and message identity; clearing, navigation and component teardown cancel stale work so an old timer cannot query a null container or scroll a newer chat. Strictly identified personal draft-only shells may remain encrypted and keyless. Message-bearing, shared, Team, direct and unreadable-key cases retain their missing-key guards; sync never creates a replacement chat key.

## Recovery and final-candidate boundary

CLI recovery runs a bounded number of independent output jobs but preserves same-output order, parent dependencies, canonical identity, digest, key, authority and durable ACK checks. Web discovery skips only an immutable output already acknowledged by the server and successfully handled locally in this session; a changed identity, failed ACK or local write, unknown failure or lifecycle reset remains eligible for recovery. Genuine recovery errors remain visible. Optional stale composer-suggestion writes use a source-correlated not-stored result; authorization and storage failures remain errors.

An acknowledged root's next-version advance requires the exact authorized sealed output, preserved current-version history and wrappers, and authenticated canonical type reuse. Only N→N+1 can advance; version gaps and same-version ciphertext replacement remain denied. Unsealed streamed updates cannot overwrite the acknowledged head or recipher immutable history. A queued canonical write can settle on verified equivalent stored content; this is separate from acknowledging its typed recovery record.

Reply terminal receipts and artifact acknowledgments are independent. The scoped reference-availability API accepts an optional bounded map of required recovery versions and returns a proof only for a matching acknowledged root whose current canonical version and digest verify under fresh owner/chat/Team authority. Legacy availability requests keep their existing response. The CLI's terminal reconciliation of an updated artifact requires that durable proof, including after reconnect or another device's acknowledgment; a stored head alone cannot substitute for it. This does not turn every reply terminal receipt into a claim that all artifacts were acknowledged.

CMS transaction repairs, the client queue correction and the navigation timer guard are implementation details; their publication and exact-source verification status is recorded separately. Real factual, Events, Focus, Project and web completion/error results are recorded only in the validation document and performance report.

The queued worker compares its original submitted text with the admitted inference request, which is bound by the existing HMAC commitment. Server-resolved embed text may differ from that original text; its canonical digest must still match, and the worker checks the immutable admission commitment using its existing state read before acknowledging the queue prefix. This preserves changed-request rejection without adding a CMS round trip.
