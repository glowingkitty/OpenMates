# Native Apple parity gaps

This source audit starts at `bbf1482f15`, the last explicit TestFlight build
metadata commit found in the repository, and covers dev through `f320ea095b`.
App Store Connect release receipts are needed to identify the exact latest
published iOS and macOS source. The remote App Store build lookup was unavailable.

| Web change or pending Apple work | Apple status | Evidence and remaining work |
| --- | --- | --- |
| Dictation with an editable live transcript and normal send | Already on dev | `ce08cb23ec` includes the composer paths and focused simulator coverage. The shared transcription correction gate is on dev in `567befff59`. |
| Start rows and suggestions across workspaces | Already on dev | `eda802f789` and `ce08cb23ec` cover layout, inspiration cards and no suggestions on Tasks. |
| Reconnects and interaction performance | Already on dev | `f1f6e91b2e` and `4c59bd450f` cover authority and socket recovery. `3f96d33db4` covers sidebar redraw work and interaction budgets. Older full-unit runs had unrelated failures. Measure background recovery and performance on actual hardware. |
| Daily Inspiration defers saving until the first follow-up | Open | Opening a native start row item currently calls `createChatWith`. Session `a370` preserves the unsaved-preview regression and a shared recovery selector. Implement the preview and first-follow-up materialization through the shared core and prove encrypted persistence and reopening. |
| Daily Inspiration recovery | Native fix in the parity worktree | `d0d329d5ab` restores the server candidate set. The preserved Rust selector now lets Apple accept the current six-card set. The native candidate needs tests for personal recovery, public fallback, relaunch and account switching. |
| Static start cards and open-chat header | Implemented in the parity worktree | Fixed decorative poses replace continuous timeline refreshes. Existing hover, card navigation, loading and media controls remain wired. Simulator evidence and dev integration are pending. |
| Quiet notification audio | Already present in source | Foreground notices use `NativeHaptics` without opening an audio session. Silent mode and quiet-window behavior have unit coverage. APNs, physical sound and idle thermal behavior need device proof. |
| Compact fullscreen embed header and sticky follow-up | Open in the fullscreen Task | Session `7b37` holds an existing native patch. It needs current-dev integration and simulator proof of the icon corner, title/subtitle, More actions, Edit, Close, fixed rails and News/Website heading handoff. |
| Voice speech-only billing, streamed text and quiet calls | Partly shared | Dev includes the backend metering and streaming changes. Apple has live call and dictation clients and an idle-gate seam. Native speech-window parity, detector-failure behavior, quiet-call continuity and actual credits need verification. |
| Cached call feedback in five languages using the Mate voice | Open | The web client and shared delivery catalog are on dev. Verify or port native handling for waiting, answering and working, with interruption and echo suppression. |
| Signed-out record, upload and call account entry | Open | Native allows a local signed-out recording, blocks uploads inside the composer and omits the call button on the signed-out start screen. Route the requested actions to the normal account UI and cover these paths before requesting platform access. |
| Shared Report Issue and hover | Workspace and chat change in the parity worktree | `4c59bd450f` restores the form and report entry points. The native candidate shares the workspace button with the chat header and adds consistent hover and press feedback. Fullscreen actions follow the fullscreen Task. Compare pointer feedback on Mac. |
| Continue ordering with drafts on old chats | Implemented in the parity worktree | Only draft-only chats get draft priority in native Continue. The regression includes an old established chat with a follow-up draft, ten newer chats and a true draft-only chat. Simulator evidence and dev integration are pending. |
| Design document view, edit and export | Native surface absent | Apple has design icon and embroidery result rendering. The newer encrypted Design document viewer and editor require a native renderer and bindings for authorized design reads, revisions and local exports. |
| Rich Sheets | Open on the existing native surface | Apple has a sheet table, Project sheet creation and export. The formatted grid, formatting tools and rich-format round-trip need native work and evidence. |
| Hosted real-time editing | Open on the existing native surfaces | The hosted relay and shared model are on dev. Native Docs, Sheets, Slides and code views still need integration with the encrypted collaboration session, including two-user edit/presence proof. |

## Additional dev changes with native counterparts

| Change family | Apple status |
| --- | --- |
| Task embeds and edit, image zoom containment and workspace picker styling | Already on dev in `857545f1ca` and `2c192c9c1a`. |
| Workspace picker animation and modal backdrop click-through | Existing native lane in session `ab21`. Its dev integration and device proof are open. |
| Chat notice deduplication | Already on dev in `9c9467bd4a`. |
| Chat notice headline, title, avatar, dismissal and unread behavior | Shared server and native notification paths exist. Native foreground and APNs behavior for the newest changes still needs scenario-by-scenario proof. |
| Task and Specification sub-chat links, layered Project Focus and Project cards | Native Project and Task surfaces exist. New inline links, precedence, encrypted metadata and navigation need verification. |
| Project file jobs, change cards and hosted App/browser previews | Shared core and server changes are on dev. Verify native file creation, result rendering, writeback, privacy prompts and recovery. Browser-only chrome has no direct native equivalent. |
| Transcript startup, included Memories, spoken hold and screen sharing | Native call equivalents exist in part. Confirm consecutive turns, Memory consent, pause handling, platform-specific sharing and background audio. |
| Events search group and fullscreen details, video gestures, embed previews and Files pane | Native renderers exist. Verify the changed product flows against the native shell and fullscreen patch. |
| PII labels, pending scans, safety support and connection-state recovery | Native and shared paths exist. The exact new display, fallback and account transitions require checks. |
| Connected accounts and Gmail drafts | Server work is on dev. Verify native settings entry, account selection and the draft result in native chat. |

The additional inventory is a source triage. Exact build receipts, end-to-end
native runs and a full commit-by-commit disposition remain open. Retain iPhone
and iPad simulator recordings and macOS pointer evidence. Use hardware for
microphone routing, interruption and background recovery, APNs and thermal checks.
