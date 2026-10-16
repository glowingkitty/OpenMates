# Chronological skill cards inside an assistant response

The proposed layout matches the agent's actual execution. A response can emit visible text, call one or more skills, consume their results, and emit more visible text before another cycle. The current backend already preserves the position of each skill placeholder in canonical assistant Markdown. The web renderer deliberately extracts those placeholders into one newest-first group above all text.

The user subsequently approved implementing minimized skill cards at their original positions, grouping only adjacent calls. The web implementation now uses that ordering. For example:

> I will compare both sources.
>
> [Web Search A] [Web Search B]
>
> Both sources agree; I will verify the date.
>
> [Calendar Search]
>
> Here is the answer.

This represents accepted visible stream order. It does not expose internal reasoning and does not invent narration between tools: some responses genuinely contain only tool calls followed by the final answer. The existing visible thinking stream is response-wide. The new web summary discloses it once, explicitly labeled Thinking for this response, rather than inventing tool-cycle attribution.

| Concern | Recommended behavior |
| --- | --- |
| Parallel calls | Place cards in invocation/placeholder order; result completion must not move them. |
| Progress and failure | Hydrate or update the original stable embed ID in place. |
| Adjacent calls | A compact row is appropriate when no authored text separates calls. |
| Reload and other devices | Parse the same final canonical Markdown into ordered text and skill-reference runs. |
| Streaming correction or missing embed | Reconcile by source position and stable ID without duplicating prose or moving unrelated blocks. |
| Historical messages | The same parser will render existing messages chronologically; decide explicitly whether that visual migration is desired. |

The implemented web increment requires no new backend event schema or durable event log. The ordered parser and renderer preserve embed identities and canonical Markdown for live, final and reopened messages. The owning Chats and Processing Feedback Specifications now describe chronological groups and expandable summaries. Focused parser and rendered CI checks cover convergence and disclosure. Native Apple retains its prior layout in this web increment; shared canonical content and early routing remain compatible. See the [response UI Plan](../assistant-response-ui/plan.yml) for accepted scope and verification.

Original source evidence (the investigated source, before the implemented renderer and queued steering changes):

- `backend/apps/ai/processing/main_processor.py`: skill placeholders at 6455–6465 and 6528–6536; visible text at 6567–6591; repeated tool/model cycles at 6897–6905; parallel search batches at 7050–7270.
- `backend/apps/ai/tasks/stream_consumer.py`: cumulative stream order at 2704–2713 and 6125–6137; thinking is separate at 6064–6112.
- `frontend/packages/ui/src/services/streamingMessageBlocks.ts`: extraction at 98–123; newest-first top group at 271–316; prepending at 444–449.
- `frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts`: final canonical content at 1015–1042; `ChatHistory.svelte` rebuilds from that content.
- `specifications/features/chats/specification.yml`: current top-group contract at 163–168 and 237; `streamingAppSkillGroup.test.ts` asserts it.
- Native `ChatView.swift` likewise renders top-level skill embeds before assistant Markdown.

For follow-ups, keep normal queuing distinct from explicit steering. [Codex documentation](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan) distinguishes adding instructions to the current run from waiting for the next run. [Cursor's SDK](https://cursor.com/docs/sdk/typescript) also injects a steer into the current run and reports when it must remain a follow-up. OpenMates should retain completed tool results, check safety and context gates, and consume a steering revision once at a safe boundary.
