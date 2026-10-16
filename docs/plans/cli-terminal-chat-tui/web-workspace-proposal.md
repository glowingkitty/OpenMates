# Terminal UI workspace proposal

Date: 2026-10-01. Planning Task: TASK-4869.

User goal: “Let’s plan out how we can bring the terminal ui of OpenMates much closer to the OpenMates web app.” This includes a terminal chat header before the first message, and terminal versions of the chat workspace, Projects, Workflows, and Tasks.

The user approved implementation on 2026-10-01 with these requirements: the web-style sidebar exists and is closed by default; terminal chat headers use the web chat's category colors; implementation is tested and terminal recordings are delivered before deployment. The foundational increments below are accepted; advanced authoring and later file-mutation increments remain follow-on work. OpenMates Tasks owns execution status and dependencies.

## Recommendation

Build a shared terminal workspace with the web app's navigation, information hierarchy, object relationships, and actions. Adapt the presentation to terminal cells: compact banners, readable message blocks, selectable cards, tab strips, lists, and optional detail panes. Keep the current client, encryption, and terminal lifecycle as the foundation.

Start with the shared shell and a complete chat experience. Projects, Tasks, and Workflows can then reuse navigation, selection, filtering, forms, and detail components. Matching those interactions gives more lasting parity than separately decorating each existing screen.

## Current implementation and web reference

| Area | Current terminal implementation | Web reference and opportunity |
| --- | --- | --- |
| Shell | `tui.ts` switches between full-screen views; `tuiRenderer.ts` wraps one scrolling body and one footer. | `Header.svelte` shares workspace navigation and sidebar affordances. Use a common shell with workspace-specific content. |
| Chat | Welcome wordmark, session message rendering, public examples, and streaming. The inspected TUI state has no active chat ID or chat metadata; the send handler does not retain/pass the returned chat ID. | `ActiveChat.svelte` supplies the empty-chat welcome. `ChatHistory.svelte` places `ChatHeader.svelte` above messages. Add persisted chat selection, correct continuation, and metadata-driven headers. |
| Projects | Client methods and deterministic CLI commands exist; there is no Projects TUI screen in the inspected screen union. | `ProjectsPage.svelte` has project selection and Overview / Files / Tasks detail tabs. |
| Tasks | List/detail views and create, edit, reorder, start, done, block, unblock, skip, and delete actions exist. Some forms suspend the TUI for shell prompts. | `TasksPage.svelte`, `TaskBoard.svelte`, and `TaskDetailContent.svelte` provide five status columns, filters, split detail, relationships, and activity. |
| Workflows | List/detail, Graph / Runs, node expansion, title/config editing, run, refresh, and cancel exist. Graph rendering currently connects array-ordered nodes with a vertical bar. | `WorkflowDetailPage.svelte` uses Template / Runs, a stable identity header, and enable/run controls; the workflows route composes the graph/editor using `WorkflowGraphRenderer.svelte`. Preserve actual graph edges and branches in the terminal projection. |

The existing terminal Plan describes some capabilities that are ahead of the inspected code, including recent-chat selection and active chat continuation. Verify source when implementing; treat those as foundational work where still missing. The web Workflows home currently has a Search control whose handler reports unavailable search, so functioning workflow search would be an additional capability to review.

Reference documents: [existing terminal Plan](plan.yml), [design guidance](../../../DESIGN.md), and [CLI parity guidance](../../architecture/platforms/cli-feature-parity.md). Related contract bundles are `specifications/surfaces/cli` and `specifications/features/{workspace-shell,projects,tasks,workflows,workflows-ui}`. Their approval and assertion coverage must be checked when converting this proposal into implementation; the proposal does not claim they already approve the new terminal behavior.

## Shared shell

The web navigation order is Chats, Apps, Projects, Tasks, Workflows. Mirror available destinations and account/feature gating. The initial requested implementation covers Chats, Projects, Tasks, and Workflows; Apps should reuse its existing client surface when taken up as a separate increment.

```text
+----------------------------------------------------------------------------------+
| OpenMates   [Chats]  Apps  Projects  Tasks  Workflows                 Connected     |
+--------------------+-------------------------------------------------------------+
| > New chat         | +---------------------------------------------------------+ |
| Search chats       | | [chat] New chat                                         | |
|                    | | What would you like to work on?                         | |
| Recent             | | Choose an example, continue a chat, or write below.     | |
|   Trip planning    | +---------------------------------------------------------+ |
|   Research notes   |                                                             |
|   Website update   | Continue: Trip planning   Research notes                    |
|                    | Examples: Learn something   Plan a trip                     |
|                    |                                                             |
+--------------------+-------------------------------------------------------------+
| > Ask anything...                                                               |
| Tab focus   Enter send   Ctrl+P actions   @ attach                                |
+----------------------------------------------------------------------------------+
```

The example is conceptual; its text and dimensions are not a frame fixture. Use the existing greeting, recommendations, and account behavior where available. Home cards disappear as the conversation begins. An optional inspector opens only when needed, such as for an embed or selected object.

Initial layout candidates: below about 90 columns, show one main pane with navigation as an overlay; at 90–129, allow sidebar plus content; at 130 and above, allow an optional inspector if each pane retains readable width. Short terminal heights also collapse secondary content. Tune these from representative frames, including 48×16, 80×24, 100×30, and 140×40.

The sidebar is closed on startup at every terminal size and opens only on an explicit toggle. Use existing design-token roles: product blue for identity, orange for the focused action, neutral text and separators, and the exact web category-gradient colors for chat banners. Provide monochrome and plain ASCII fallbacks. Large wordmark art belongs on the welcome screen when space permits; normal chat banners need only a small category mark and readable text.

## Chat header and chat workspace

The web distinguishes the empty welcome screen from the metadata banner of an actual chat or draft. The requested terminal version can put a compact New chat card in the same position before first send, then replace it with the real chat header.

Header lifecycle:

1. **Empty:** `New chat` plus a short welcome and existing example/continue actions. Do not invent a generated title, category, or creation timestamp.
2. **First send accepted/pending:** show `Creating new chat…` above the first user message. Preserve the returned chat identity and any available metadata while streaming.
3. **Metadata ready:** render category mark, title, a wrapped summary, relative started / published / saved time as appropriate, and applicable Draft / Example / Shared / Incognito labels. Labels must reflect the real mode and supported contract. Show Project context only when linked.
4. **Failure:** display the actual error, including `Not enough credits` when applicable, with a usable composer and retry action. Missing metadata never hides existing messages.
5. **Reopen:** hydrate the same header from decrypted saved metadata. Title/summary editing follows ownership and read-only rules and syncs through existing contracts.

```text
+--------------------------------------------------------------------+
| [travel] Planning a trip to Japan                                   |
| Compare routes, places to stay, and a realistic budget.              |
| Started just now                                                   |
+--------------------------------------------------------------------+

You
  Help me plan two weeks in Japan.

Sophia
  Let's start with your travel dates and the places you want to visit.
```

Treat this as a transcript header: show it before the first message and let it scroll with history as on the web. Reserve roughly 4–7 rows when room permits; wrap or expand longer summaries. On short screens use a two-row variant with details available through an action. A compact shell breadcrumb can retain the chat title during scrolling, while Home returns to the full header. Metadata changes must preserve scroll position.

The chat workspace also needs recent chats/search, opening existing conversations, per-chat composer state, safe draft restoration, multiline editing, attachments, streaming/stop/retry states, follow-up suggestions, compact embed cards, and an embed detail pane. Reuse encrypted draft and chat APIs. Preserve existing logged-out and example-continuation semantics and guard in-flight results when the user switches chats. Account changes clear account-scoped views.

## Projects

Use a selectable project list and a detail workspace with **Overview / Files / Tasks**, matching the web labels. Overview contains the project title/description, readme, and existing new chat/workflow/plan actions; stored/remote items and the task board are reached through Files and Tasks. Open linked objects in their workspace with a clear route back to the project.

Files becomes a navigable list/tree with breadcrumbs, search, sorting, stored/remote source labels, preview, and explicit actions. Use existing file resolution, remote availability, review, and approval contracts. Build browse/open first, then upload/copy/move/edit through the existing operations. Starting a chat from a Project passes that context into `sendMessage`; selecting a project for browsing does not silently attach every file.

## Tasks

On sufficiently wide screens, show the web's **Backlog / Todo / In progress / Blocked / Done** board. At intermediate widths, allow horizontal column navigation; on narrow screens, default to grouped lists or a selected status tab. Keep the focused task visible when the board updates.

Cards show a readable title, short ID, assignee, priority where present, and relevant due/blocker context. Selecting a card opens details with status/assignee editing, description, due date, tags, linked chat/Project/Plan, dependencies, and chronological activity. Render workflow-projected tasks according to their existing read-only rules.

Replace drag-and-drop with a status picker or explicit move action. Put create/edit/activity forms inside the TUI so the workspace remains visible. Distinguish an intended or queued action from a confirmed update; show claim conflicts and blockers using the existing delivery rules. Keep lifecycle actions consistent with the web and CLI.

## Workflows

Keep the workflow list/sidebar and align detail tabs to **Template / Runs**. The terminal Template view uses compact selectable node cards plus a node inspector. Draw connectors from graph edges; show branches with labels and explicit destinations rather than flattening a branching graph into a sequence.

```text
Daily rain check                    Enabled     Next run: tomorrow
[Template]  Runs

[Schedule: every morning]
             |
[Weather: forecast]
             |
[Decision: rain expected?]
     yes ----+---- no
      |            |
[Notify me]       [End]

Enter node details   Actions: Run now / Edit / Export
```

Use schema-driven fields for supported step configuration; keep advanced YAML/JSON accessible as an explicit expert action. Runs shows selectable run history, per-node state, waiting/input requests, output, errors, and cancel/retry actions where supported. A historical run uses its recorded version, not a newly edited template. Reuse existing authoring, run, validation, and retention behavior. Templates, AI-assisted authoring, reorder/branch editing, and sharing are later increments after basic navigation and execution are solid.

## Keyboard and state model

Give every screen the same focus rules: Tab/Shift+Tab changes pane/control focus; arrows move selections; Enter activates the focused control; Escape closes the current overlay or returns one navigation level; PageUp/PageDown scrolls the focused content. Ctrl+P opens searchable workspace actions. Keep existing slash commands usable from the composer and make important actions discoverable in the footer.

Only interpret letter shortcuts when a list/action pane has focus. Text fields accept normal typing, paste, IME text where supported, and multiline input. Preserve selection, scroll, and drafts per workspace/object when navigating away and back. Destructive and permission-sensitive actions reuse existing confirmations/reviews inside an overlay; they remain explicit user actions.

## Implementation approach

- Keep `TuiTerminal` responsible for terminal lifecycle, resize, and capability handling; retain a pure rendering layer for deterministic testing. Extract focused layout and component helpers as the shared shell grows.
- Separate workspace/object routing, focus, composer state, and overlays from decrypted object data and network effects. Give chat, Projects, Tasks, and Workflows controllers bounded loaders and action handlers instead of extending one global key handler indefinitely.
- Reuse `OpenMatesClient`, task decryption/delivery, project file access, encrypted draft APIs, and existing workflow contracts. Add only the event/adaptor hooks actually needed. Cache/list loading should be bounded and preserve owner/team scope.
- Handle delayed responses by object identity/request generation. Keep chat transcript scrolling independent of metadata updates, and preserve list focus through live changes. Use existing sync events where exposed, and explicit refresh/bounded active-view refresh where they are not; do not assume complete live subscriptions already exist.
- Budget layout in display cells, including CJK, emoji, combining marks, wrapping, and paste. Sanitize untrusted control sequences before terminal rendering. Resize must fit the actual terminal instead of forcing a larger virtual minimum width.
- Start with the current renderer. Revisit a rendering dependency only if the shell prototype demonstrates a concrete width/input/composition limitation; the architecture should permit that decision without replacing the client layer.

## Suggested delivery sequence

| Increment | Deliverable | Dependency |
| --- | --- | --- |
| 1. Shell and chat foundation | Common navigation/focus, compact welcome/header states, retained chat identity, reopen/continue, responsive frame layout. | Confirm proposed behavior against existing contracts. |
| 2. Chat workspace | Recent/search, drafts and multiline composer, attachments, embed inspector, streaming/stop/error actions. | 1 |
| 3. Tasks workspace | Responsive board/grouped list, filters, in-TUI forms, detail/relationships/activity. | 1; links use 2 when navigating to chat. |
| 4. Projects workspace | Project list, Overview/Files/Tasks, linked navigation and explicit Project chat context; file mutation actions follow browse/open. | 1, 2, 3 |
| 5. Workflows workspace | Template/Runs navigation, edge-aware graph, node inspector/forms, run history and execution states; advanced authoring follows. | 1; links use 2 and 4 where relevant. |

These are increments, not a second Task ledger. Once the direction is accepted, create implementation Tasks only for independently deliverable scope and record dependencies there. Start with increment 1 to review the shared interaction language before expanding all workspaces.

## Acceptance and verification for implementation

The first increment should demonstrate: a useful header before first send; the processing-to-generated-header transition without disturbing messages or scroll; reopening a saved chat; two sends continuing the same account chat; preserved composer text on workspace navigation; and usable layout/focus at narrow, normal, and wide terminal sizes. Existing guest/example behavior must remain intact.

For later increments, verify representative flows: create/move/block a task and read its activity; open a Project file and start a Project-linked chat; inspect a branching workflow and a historical run; follow related-object links and return with selection intact. Cover loading, empty, error, read-only, queued, and reconnecting states for affected screens.

Extend `tests/tui.test.ts`, `tests/tuiExampleContinuation.test.ts`, and the fake-terminal interaction pattern in `tests/tuiWorkflowInteraction.test.ts`. Add focused controller/layout tests and relevant product E2E coverage as behaviors land. Use synthetic fixtures for layouts and deterministic interactions; run product CLI/backend checks through the existing isolated GitHub CI coordinator. Checks strictly requiring real inference use the authorized dev-host workflow with disposable state. A real-terminal smoke should cover resize, paste, cursor/alternate-screen cleanup, and the chosen key bindings. No product code or new implementation verification is part of this proposal-only change.
