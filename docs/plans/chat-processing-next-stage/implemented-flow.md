# Prepared privacy and independent chat completion

This increment implements the user-approved Plan in `plan.yml`. Its latency acceptance is separate from correctness: deployment and measured default-Gemini TUI results precede equivalent web measurements. The retained baseline misses the 1.5-second selected-Mate and 2–3-second factual authored-stream targets; candidate code is not evidence that those targets are met.

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
  J2 --> Hydrate[Authorize and load selected context concurrently]
  Need -- complete empty context --> Main[Main: required instructions and relevant conversation]
  Hydrate --> Main
  Main --> Stream[Stream authored text and ordered skill events]
  Stream --> Terminal[Authoritative response terminal: stop active label and glow]
  Terminal --> Persist[Required encrypted reply persistence: next Send ready]
  Terminal --> Post[Independent postprocessing]
  Post --> Metadata[Later header title/summary and follow-up chips update and persist]
```

Warm-up sends neither draft text nor inference. Protected information is filtered locally before request content is transmitted. The paired cleartext-processing/encrypted-durability admission already existed; this increment removes avoidable preparation and completion dependencies rather than introducing unencrypted durable storage.

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

The wrapper owns authenticated source binding and gates. Discovery caches are data, not permission or positive-balance caches. Client privacy configuration is not indiscriminately forwarded to the model.

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

This request excludes unrelated private bodies and full tool schemas. Only complete authoritative context can justify skipping detailed selection. A short message or a particular question word cannot establish that context.

## Jev stage 2

```mermaid
flowchart LR
  First[Validated stage-one decisions and selected apps] --> J2[Jev stage 2 when needed]
  Skills[Relevant skill schemas; Focus definitions; public app Memory guides] --> J2
  User[Authorized Memory / Workflow discovery and Project Focus catalogue] --> J2
  Active[Required active / explicit context; related Task / Plan / recent-work metadata with provenance] --> J2
  J2 --> Selected[Selected skill / Focus / Memory / Workflow / related-work IDs and revisions]
  Selected --> Bodies[Fresh authorization then independent selected-resource reads / decryption]
```

Selected-resource hydration means loading the specific authorized resource bodies chosen by this stage. Independent loads overlap; selection must precede any load whose resource identity is not known yet. Already active or explicitly selected resources may prepare earlier, while their required authority remains current.

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

Unused tool, artifact-format and product-capability guidance may be omitted only when complete response requirements justify that omission. Initial factual requests and factual follow-ups use the same eligibility rules; necessary referential history stays. Missing ethics or mandatory privacy causes a reload and then prevents inference if still unavailable. Compactness does not change the configured Gemini or thinking policy. The compact assembly is currently verified for English, French and German; other languages keep the complete instruction path.

## Postprocessor request and independent delivery

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

The main-generated composer suggestion is distinct from postprocessor chips. Completion ends the active response presentation; required encrypted persistence controls Send readiness. Metadata arrival remains observable through bounded owned subscriptions, continues updating headers and suggestions, and cannot revive a terminal response or overwrite a newer turn's suggestion. The stage-one initial title has its own early delivery path. Later versioned title/summary updates may still apply during the next turn; follow-up chips and composer suggestions stay bound to their source turn. Unversioned initial generated titles use the existing guard against replacing an already stored title.

## Cache and authority boundaries

| Data | Preparation / retention | Freshness requirement |
| --- | --- | --- |
| Shipped Mate, app, skill, Focus and Memory definitions | Process cache by deployment/configuration revision | Valid required instruction sections; reload invalid bundles |
| Encrypted owner/Team discovery | Existing scoped Dragonfly cache, two sliding hours | Mutation generation/source revisions plus fresh selected access |
| Personal privacy source and compiled options | Device-local RAM, at most two sliding hours | Durable aggregate generation and fresh session/device/scope validation on Send |
| Selected private context | Existing authorized transient transport and consent-bound retention | Exact source revision, owner/Team, turn and current authority |
| Access, consent, spending and execution permission | Checked at required boundaries | No two-hour positive permission or balance cache |
| Late answer metadata | Client-encrypted persistence and bounded delivery | Exact source turn, metadata versions and current account/chat/Team |

Directus development schema freezing removes repeated schema cloning while preserving supported schema and permission invalidation. Out-of-band generation schema setup requires explicit cache clearing or CMS recreation. Performance claims must use correlated deployed request phases, not the process-wide profiler's percentage alone.

## Verification status

Focused backend, CLI and web correctness checks pass. The scoped CLI privacy/terminal-streaming and web processing/PII integration checks pass; matching auth and first-admission recovery results are retained. Later annotation/formatting fixes preserve executable test logic, and the merged CLI passes focused units and its configured build. Deployment and new real-Gemini latency/error acceptance are pending. The WebSocket delivery-state repair is held separately for its owner and is excluded from this timing candidate. The reported CMS transport retries and signed-out activity requests are not established as one shared cause.
