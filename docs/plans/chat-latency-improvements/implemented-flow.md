# Chat processing architecture

The architecture revision (`fa6b90c`), Google transport repair (`e71c72b8`), immediate admission changes (`2453d85d`), first measured SDK/auth/simple-turn fixes (`7a250696`), composer focus repair (`df30b916`), and idle authenticated TUI connection / bounded Project projection changes (`ab78d61b`) are deployed to development. Actual TUI measurements still miss the latency targets; no successful timing acceptance is claimed yet. Timing targets are 1.5 seconds from Enter/Send to selected-Mate paint, and 2–3 seconds to authored text for an ordinary factual request. The interactive TUI is measured first, then web. Tool progress, final response, persistence and command exit are separate measurements.

```mermaid
flowchart TD
  Focus[Web focus or microphone / TUI startup] --> Prepare[Prepare invisible chat UUID and key; warm authorized discovery]
  Send[Enter / Send] --> Optimistic[One user row; clear submitted composer snapshot]
  Optimistic --> Admit[One encrypted chat_turn_admit frame]
  Admit --> Durable[Fresh authentication; atomic chat and first-message preparation; protocol admission]
  Prepare -. reused when ready .-> Admit
  Durable --> Router[Reserved app_ai_routing worker]
  Admit --> Headers[Correlated routing metadata]
  Headers --> Router
  Headers -. required discovery fails .-> Failure[Bound encrypted context-failure marker]
  Failure --> End[Release exact active task; terminal failure event; no assistant text]
  Router --> Stage1[Jev stage 1: complexity, Mate, apps, Projects, public decisions]
  Stage1 --> Resolve[Resolve permitted model and publish selected Mate]
  Resolve --> Paint[Client paints Mate + Thinking]
  Resolve --> Handoff[Encrypted 120-second routing snapshot; original turn identity]
  Handoff --> MainQueue[Main worker; fresh snapshot and execution checks]
  MainQueue --> Complete[Complete correlated private-detail hydration and fresh execution checks]
  Complete --> Need{Detailed selection needed?}
  Need -- complete empty context --> Minimal[Assemble required answer context]
  Need -- capabilities, active context or uncertainty --> Stage2[Jev stage 2: selected skills, Focus, Memory, Workflows, related work]
  Details[Authorized active or explicit private details] --> Complete
  Stage2 --> Hydrate[Authorize and load selected resources in parallel]
  Hydrate --> Minimal
  Minimal --> Main[Main model streams authored text and ordered tool cycles]
  Main --> Output[Client renders text and skills at their source positions]
  Main --> Final[Billing and durable completion; successful terminal metadata]
  Final --> Ghost[Separate composer suggestion; client encrypts for sync]
  Final --> Post[Postprocessor metadata and separate followup chips]
```

Prepared identity does not create an unwanted visible empty chat. With the durable protocol enabled, a cold request creates the chat and commits its message in the same admission. When the recovery cutover epoch is zero, first-frame admission atomically prepares the new chat and first encrypted user message before acknowledging `LEGACY`; subsequent inference follows the established dispatch path. Existing chats and human-only Team conversations keep their existing gates. The latency changes do not enable a global recovery cutover. Capability negotiation retains the established protocol for older APIs. Deferred routing/private-detail frames currently apply to first ordinary Personal turns; existing-chat, Team, explicit-Project and attachment paths retain their complete context and established gates. This avoids expiring a queued turn's required context while it waits behind a long response.

With `chat_turn_context_selection_details_v2`, the routing continuation needs only the completed authorized Project candidate list. Task candidates, accepted Plan context, Project Focus discovery and the connected-account directory arrive in the separately correlated details continuation. These reads run concurrently and must complete before detailed selection or main-context assembly; they do not delay stage-one Mate feedback. Failed or incomplete Project discovery retains the complete path. Older APIs receive the established full routing payload.

The preprocessor wrapper receives the authenticated request and server configuration. Cached discovery is data; access, source revision, consent, credit and execution checks remain authoritative.

```mermaid
flowchart LR
  Identity[Chat, user, Team, message, turn and recovery identities] --> Pre[Preprocessor wrapper]
  Conversation[Current text; bounded history and summary; content-free skill ledger] --> Pre
  Overrides[Explicit model, Mate, skill, Focus and Memory overrides] --> Pre
  Discovery[Project candidates; available memory keys; connected account directory] --> Pre
  Active[Fresh active Focus / Project binding; accepted Plan and Task references] --> Pre
  Config[Public app and Mate catalogues; routing defaults; safety and credit policy] --> Pre
  Pre --> Route[Compact routing, permitted model resolution and early Mate feedback]
  Route --> Conditional[Conditional detailed selection and selected context]
```

Jev's first request excludes unrelated private bodies and full tool schemas. Its validated public decisions can authorize skipping the detailed pass only when the fresh active-context snapshot is complete and empty.

```mermaid
flowchart LR
  Messages[Bounded conversation and summary] --> J1[Jev stage 1 request]
  Ledger[Content-free skill ledger and prior topic] --> J1
  Catalogue[Compact app capability descriptions and Mate choices] --> J1
  Projects[Authorized Project discovery metadata and explicit routing intent] --> J1
  J1 --> Decision[Complexity; Mate; apps; Project outcome; public safety/language decisions; need flags]
  Decision --> Model[Exact-chat / tier preference / configured model resolution]
  Model --> Early[Selected Mate event before specialist or detailed selection]
```

Jev's detailed request sees the relevant catalogue. Required active or explicitly supplied context can load while routing runs; resources whose IDs are chosen by this pass load afterward. Main revalidates selected related-work snapshots rather than issuing a third selector inference.

```mermaid
flowchart LR
  Stage1[Validated stage-one decisions and selected app IDs] --> J2[Jev stage 2 request, when needed]
  Skills[Selected apps' skill schemas and Focus definitions] --> J2
  Memories[Relevant public app Memory guides and authorized Memory metadata] --> J2
  Project[Relevant Project Focus catalogue and active or explicit context] --> J2
  Workflows[Authorized Workflow discovery metadata] --> J2
  Related[Needed Task, Plan and recent-work summaries with provenance] --> J2
  J2 --> Selection[Skill, Focus, Memory, Workflow and related-work IDs / revisions]
  Selection --> Load[Parallel selected-resource authorization and hydration]
```

Minimal main context retains the instructions needed to answer correctly. It omits unrelated private Project/Task/Workflow bodies and unused selected app guidance; it preserves mandatory safety, privacy, formatting, questions, model policy and selected context. A confirmed objective English factual first turn with complete empty context omits the empty Task runtime and its create tool. Unknown intent, actions, explicit Task dependencies and incomplete context retain the full path. The last qualified main prompt contained 7,163 tokens. The next candidate also omits only code, document and plot formatting sections for a positively proved objective factual first turn with zero final tools and no selected private or artifact context. Discovery metadata alone does not force artifact instructions back into the prompt. Unknown intent, selected context, relevant history, attachments and actions retain those sections; mandatory answer and composer-suggestion guidance remains. Token and timing savings are not yet measured.

```mermaid
flowchart LR
  System[Mate and language; required safety, privacy, output and question instructions] --> Main[Main model request]
  User[Current message; required history / summary; relevant attachments] --> Main
  Tools[Forwarded tool schemas; selected Focus and app Memory guidance] --> Main
  Selected[Authorized selected Memory / Workflow / Project bodies and fresh related references] --> Main
  Agent[Current tool results and steering at safe boundaries] --> Main
  Policy[Resolved model, region and thinking level] --> Main
  Main --> Stream[Authored chunks, visible reasoning and ordered tool events]
  Main --> Suggestion[Optional trailing contextual suggestion metadata]
  Suggestion --> Extract[Strip before display and answer storage; deliver separately on successful completion]
```

Postprocessing remains separate from answer streaming and the main-generated composer suggestion.

```mermaid
flowchart LR
  User[User request] --> Post[Postprocessor request]
  Answer[Final authored assistant answer and required history] --> Post
  Metadata[Existing title, summary, tags, language and settings] --> Post
  Catalogue[Available app metadata] --> Post
  Post --> Chips[Followup request chips and new-chat suggestions]
  Post --> Chat[Title / summary / tags / app recommendations / safety metadata]
```

| Data | Preparation and retention | Freshness boundary |
| --- | --- | --- |
| Shipped skill, Focus and app Memory definitions | Process RAM at startup, keyed by configuration revision | New deployment / process |
| Workflow discovery | Vault-encrypted Dragonfly, two sliding hours | Nonexpiring mutation generation plus fresh access |
| Encrypted Project summaries | Dragonfly, two sliding hours | Fresh owner/Team ID/version/time watermark; keys and wrappers remain live |
| Project Focus discovery | Opaque item IDs and revisions, two sliding hours | Fresh scoped listing; private bodies remain live |
| Team Memory discovery | Key metadata only, two sliding hours | Fresh Team role and source versions; no cached item body |
| Personal available Memory keys | Device-local index warmed on focus | Current keys reread for Send |
| Selected private details and routing handoff | Existing authorized transport; new phase/snapshot payloads Vault-encrypted for 120 seconds | Exact owner, Team, device/turn, source revision and consent |
| Approved user Memory content | Existing consent-bound chat-specific encrypted retention, default 24 hours | Scope, revision, revocation and chat eviction |

Project/Focus/Team-memory cache hits still require a small fresh Directus watermark read. These indexes reduce repeated full metadata reads; they are not permission caches. No warm-up sends draft text or invokes an AI model. The TUI also prepares a separate one-use authenticated send connection with a 45-second lifetime. Borrowing requires the same account, session, refresh-cookie authority, device key, Team/key scope and socket options, plus a fresh persisted-state recheck. A foreground send cancels an unfinished optional connection before required preparation; a ready matching connection can be borrowed once. Token expiry renewal under the same refresh-cookie authority does not discard an already-authenticated live connection.

## Measured TUI timing before the next optimization

These are actual PTY Enter-to-paint measurements of “What’s the capital of Spain?”, with the same successful Google Gemini 3.8 Flash model and LOW thinking verified against the exact task and chat in server logs. Every sample completed without app skill calls. The two warmed samples after `7a250696` used a 20-second idle before Enter; the first also followed worker restart. They are individual observations, not a representative percentile or an apples-to-apples improvement claim.

| Runtime / condition | Optimistic user row and composer clear | Selected Mate | First authored text | Provider request → authored paint | Acceptance |
| --- | ---: | ---: | ---: | ---: | --- |
| `2453d85d`, cold composer | 28 ms | 11,088 ms | 15,829 ms | 2,776 ms | Missed |
| `2453d85d`, warmed | 28 ms | 3,168 ms | 5,634 ms | 1,578 ms | Missed |
| `7a250696`, warmed after restart | 28 ms | 5,353 ms | 8,939 ms | 2,076 ms | Missed |
| `7a250696`, warmed, subsequent request | 29 ms | 2,992 ms | 5,740 ms | 1,976 ms | Missed |

The last sample spends 2,992 ms before selected-Mate paint, then 772 ms before the main provider request and 1,976 ms from that request to authored paint. The main worker reused the original validated no-Project decision and skipped the second Jev phase. Fresh credit verification took about 53 ms in that worker and 67 ms in routing; the first post-restart sample took about 506 and 527 ms respectively. The delay preceding its first credit-check substep is not separately instrumented.

The deployed `ab78d61b` changes remove two discarded Project-focus reads, parallelize fresh Project key-wrapper projections with a bound of eight, and prepare a separately owned one-shot authenticated TUI send connection while idle. They retain current access/credit checks. Their timing benefit remains unverified: the first actual warmed run admitted the message but failed before any model request. Command completion and postprocessing are recorded separately from first answer paint.

In that failed run, the user row painted at 30 ms and the admission frame left the client at approximately 935 ms. Required Project discovery returned HTTP 503 at approximately 1,345 ms. Admission completed at 1,484 ms; the SDK closed the socket about 24 ms afterward when the pending Project promise rejected. Routing then waited 20 seconds for client context and main repeated that wait, terminating approximately 42.6 seconds after Enter. These are failure timings, not inference latency.

The source of the observed authentication churn was a shared profile cache validator treating an explicitly null email-encryption field on legacy/paired accounts as an incomplete profile. It evicted valid cached profiles; concurrent cache-miss requests refreshed credentials, and successful refresh results were visible before their successor security rows were durably published. The next candidate distinguishes a known null field from a missing field, waits for an existing refresh publication using the existing bounded coordination window, and preserves fresh source/successor and passkey checks. It also reports required-context failure through a sealed, exact-turn marker and a matching terminal event, preventing the two silent waits and clearing pending UI state without creating an empty assistant response. The profile and refresh repairs do not establish a positive authorization cache.

The Personal Memory row and account-settings reads remain sequential in this revision. Both can rotate a shared refresh-cookie jar, and account settings supply a one-use auth receipt for the exact Memory snapshot. Parallelizing them requires coordinated response ownership; a plain concurrent call is not safe. The measured warmed preparation cost is about 588 ms (241 ms rows, 14 ms decryption, 333 ms settings/auth).
