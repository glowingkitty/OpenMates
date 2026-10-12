# Chat processing architecture

Implementation candidate; isolated checks and live latency measurements are still pending. Timing targets are 1.5 seconds from Enter/Send to selected-Mate paint, and 2–3 seconds to authored text for an ordinary factual request. The interactive TUI is measured first, then web. Tool progress, final response, persistence and command exit are separate measurements.

```mermaid
flowchart TD
  Focus[Web focus or microphone / TUI startup] --> Prepare[Prepare invisible chat UUID and key; warm authorized discovery]
  Send[Enter / Send] --> Optimistic[One user row; clear submitted composer snapshot]
  Optimistic --> Admit[One encrypted chat_turn_admit frame]
  Admit --> Durable[Fresh authentication and durable encrypted commit]
  Prepare -. reused when ready .-> Admit
  Durable --> Router[Reserved app_ai_routing worker]
  Admit --> Headers[Correlated routing metadata]
  Headers --> Router
  Router --> Stage1[Jev stage 1: complexity, Mate, apps, Projects, public decisions]
  Stage1 --> Resolve[Resolve permitted model and publish selected Mate]
  Resolve --> Paint[Client paints Mate + Thinking]
  Resolve --> Handoff[Encrypted 120-second routing snapshot; original turn identity]
  Handoff --> MainQueue[Main worker; fresh snapshot and execution checks]
  MainQueue --> Need{Detailed selection needed?}
  Need -- complete empty context --> Minimal[Assemble required answer context]
  Need -- capabilities, active context or uncertainty --> Stage2[Jev stage 2: selected skills, Focus, Memory, Workflows, related work]
  Details[Authorized active or explicit private details] --> Stage2
  Stage2 --> Hydrate[Authorize and load selected resources in parallel]
  Hydrate --> Minimal
  Minimal --> Main[Main model streams authored text and ordered tool cycles]
  Main --> Output[Client renders text and skills at their source positions]
  Main --> Final[Billing and durable completion; successful terminal metadata]
  Final --> Ghost[Separate composer suggestion; client encrypts for sync]
  Final --> Post[Postprocessor metadata and separate followup chips]
```

Prepared identity does not create an unwanted visible empty chat. A cold request creates the chat and commits its message in the same admission. Capability negotiation retains the established protocol for older APIs. Deferred routing/private-detail frames currently apply to first ordinary Personal turns; existing-chat, Team, explicit-Project and attachment paths retain their complete context and established gates. This avoids expiring a queued turn's required context while it waits behind a long response.

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

Minimal main context retains the instructions needed to answer correctly. It omits unrelated Project/Task/Workflow discovery, unused app guidance and unavailable tool-only instructions; it preserves mandatory safety, privacy, formatting, questions, model policy and selected context.

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

Project/Focus/Team-memory cache hits still require a small fresh Directus watermark read. These indexes reduce repeated full metadata reads; they are not permission caches. No warm-up sends draft text or invokes an AI model.
