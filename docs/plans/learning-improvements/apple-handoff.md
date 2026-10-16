# Prompt for the Mac agent

Implement and verify Apple parity for the wiki learning and phased Study improvements deployed to OpenMates dev. The user approved implementation, testing and dev deployment, then requested this handoff for their Mac agent. Publishing TestFlight or changing production needs separate authorization.

Start from current `dev` containing product commit **911e2f0176a589a7e82894a0edb2ae33939e9a0f**. Reuse your own assigned Mac workspace/session, or obtain one through `scripts/sessions.py` before editing. Read `AGENTS.md`, applicable Apple/privacy/embed rules and the `ios` skill. Keep the native implementation consistent with the rendered web source and preserve concurrent edits. Do not use the Linux session `0c78` or another task's workspace.

Tracking: engineering Project `96033196-e4b1-431e-b773-ba221e952fed`; Linux work TASK-2518 and TASK-430. Create/link a Mac Task for native implementation in your own chat. Approved scope is in `docs/plans/learning-improvements/plan.yml`; current contracts are `feature.wikipedia-mentions@1` and `feature.focus-modes@2`, including the existing `focus-modes.learning.progress-and-suggestions` assertion. Apple implementation is the remaining client delivery step; the Linux deliverable was this handoff.

## Match these behaviors

1. A wiki link's visible words match its article's canonical name. Normalize Unicode, underscores, whitespace and case; allow a trailing disambiguation suffix, e.g. `Mercury (planet)` for visible `Mercury`. Do not link `Einstein` to `Albert Einstein`, or a concept to a differently named article. Recheck the fetched canonical title after redirects. Mismatches render ordinary text or an article-unavailable state.
2. The fullscreen article stays readable while learning suggestions load or fail. Below it, show “Learn more”, a private Study interest action, suggested learning questions, and related article titles/descriptions. Use the Study icon and existing native design tokens/components. Match responsive web behavior, keyboard/accessibility, loading, retry, failure and signed-out states.
3. A question sends exactly one normal encrypted message in the chat captured when the article opened, then closes fullscreen **only after accepted submission**. Keep the composer draft, selected model, learning policy/focus and chat context. Failure retains the article and draft for retry. Disable repeated taps while sending. Related navigation preserves the original chat. Guard account/chat changes and late callbacks closing a newer article. Without an owned originating chat, create a new chat after acceptance; never send into another user's shared chat.
4. Send `@wikipedia:<language>:<canonical_title_with_underscores> <question>`. The normal send path includes top-level `preserve_draft: true` in `chat_message_added`, including queued/offline replay. The deployed backend honors only boolean `true`, retaining the encrypted server draft without broadcasting deletion. Ordinary sends still clear drafts. Use a separate submission; do not insert the question into the live composer.
5. “I want to learn more about this” creates one encrypted `study.learning_goals` entry through the existing memory lifecycle. Only `topic` is required; do not invent difficulty or mastery. Inside the encrypted value, store `_wikipedia: { canonical_title, language, source_url }`. Deduplicate by canonical URL/language, preserving disambiguation; reuse a legacy plain goal only by exact full topic name. Saved state offers “Edit learning goal” and opens the existing entry editor. Flush the current composer draft before leaving chat for that editor; guard account/chat/article changes during the flush. Preserve hidden `_wikipedia` metadata during edits. Saving grants no conversation memory-sharing permission and asserts no assessment progress.
6. Guests can read articles and sign in for learning actions. Public suggestions are generated server-side without personal context. Never send history, age group, memories or learner data for generation. Personal teaching context applies when the chosen question goes through normal chat.

## Reuse the deployed API

- `GET /v1/wikipedia/search?query=<text>&language=en&limit=5`
- `GET /v1/wikipedia/summary?title=<canonical>&language=en`
- `GET /v1/wikipedia/learning?title=<canonical>&language=en`

Use authenticated APIClient requests. Summary fields are the proxy's flat `title`, `canonical_title`, `language`, `description`, `extract`, `thumbnail_url`, `source_url`. The current native summary model expects nested Wikipedia REST fields: update it for this wire contract, retaining appropriate backward compatibility.

Learning returns `{canonical_title, language, source_url, questions: string[], related_articles: [{title, canonical_title, language, description}], expires_in_seconds}`. The backend uses public-only GPT-OSS 120B through Cerebras, Groq fallback, validated article titles, a shared 24-hour Redis cache, miss coalescing, authenticated access and generation limits. Reuse that endpoint; add no Apple provider call or personal cache inputs. Endpoint failure preserves the article and memory action. Treat canonical identity, language and source as the bundle identity.

Web sources:

- `frontend/packages/ui/src/components/embeds/wiki/{WikiInlineLink,WikipediaFullscreen}.svelte`
- `frontend/packages/ui/src/utils/wikipediaLearning.ts`
- `frontend/packages/ui/src/services/wikipediaStudyInterest.ts`
- `frontend/packages/ui/src/components/ActiveChat.svelte`: wiki callbacks and captured origin
- `frontend/packages/ui/src/components/enter_message/MessageInput.svelte`: `sendPublicQuestion`
- `frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts`: `preserveDraft`
- `frontend/packages/ui/src/services/sendersChatMessages.ts`
- `backend/core/api/app/routes/handlers/websocket_handlers/draft_submission.py`
- `frontend/packages/ui/src/i18n/sources/embeds.yml`: wiki labels

Likely native owners:

- `apple/OpenMates/Sources/Features/Embeds/Renderers/WikiRenderers.swift`
- `apple/OpenMates/Sources/Features/Embeds/Renderers/WikiArticleModel.swift`
- `apple/OpenMates/Sources/Features/Embeds/Grouping/EmbedFullscreenContainer.swift`
- Existing chat sender/composer, encrypted app-memory store/editor, and locale generation.

Both SDKs expose `wikipedia.search()`, `.summary()`, `.learning()` and `.article()`. CLI exposes `wiki search` and `wiki show`; **no `wiki learning` command**. `.article()`/`show` preserve article content when suggestions fail.

Study `learn_topic` now has Understand → Build understanding → Guided practice → Independent check → Review; `test_knowledge` has Understand → Assess → Check gaps → Review. Use existing phase metadata/events and native notice/settings views. Check titles, progression/history, re-entry and Review; do not hardcode a five-round intake. Learner attempts supply evidence and skipped checks remain unassessed. Backend follow-ups use contextual Jev decisions and conservatively withhold uncertain answer-bearing chips. Preserve those decisions rather than regenerating locally. No new native assessment scoring, phase engine, model decision service or reminder automation is required.

## Required Mac evidence

Run focused model/unit tests, native build and Simulator interaction checks appropriate to changed targets. Extend `WikiArticleModelTests.swift`, `WikiFullscreenParityUITests.swift` and `FocusPhaseTests.swift` where relevant. Add stable accessibility identifiers matching meaningful wiki web test IDs. Verify identity/redirect mismatch, language (include Hebrew, currently absent from the native language set), image decoding, authenticated/guest/degraded states, related navigation, one question submission, failure/retry, draft persistence across reload/reconnect, encrypted memory dedup/edit, and phase history without false mastery.

Capture and review opening, question/related controls, saved state and failure state at phone and larger native sizes. The final web component passed five isolated cases without retries in run `37263413041` (resolved current-dev candidate `42a7924989dd3cbf2a61c4faec0fad34d2fd0888`), and the corrected draft candidate `4cd2cd79d2a076c6030462975dccef3bd044230f` passed eight composer cases in `37272238543`. Laptop and phone images in the wiki run's `isolated-test-results` artifact were reviewed. Final chat-flow and deployed evidence are in `docs/plans/learning-improvements/evidence.md`. Compare with the final deployed web behavior.

Deploy only your scoped native changes to dev through the session helper. Report commit, tests/build/Simulator evidence and actual remaining work. Swift compilation alone does not prove native interaction parity or TestFlight readiness.
