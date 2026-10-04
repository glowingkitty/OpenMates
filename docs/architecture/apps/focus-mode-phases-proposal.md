# Focus modes with phases

Implementation authorized in Codex chat `01a10607-989f-77e1-b08b-4dce9f7d106a`,
with the user's correction that the five-round clarification minimum is instruction
text only. Work and evidence are tracked in `docs/plans/focus-mode-phases/plan.yml`
and OpenMates Tasks TASK-6202, TASK-4703 and TASK-7858 (session 907d).

Focus modes remain text. Canonical SKILL.md YAML frontmatter adds
`phases_version: 1` and an ordered `phases` list. Each phase has a stable `id`,
`title`, multiline `instructions`, and `requirements` (`id`, `text`, optional
`type: semantic | user_confirmation`). The Markdown System prompt is global.
Project focus instruction text uses the same frontmatter format. Unphased text
keeps its existing behavior. Duplicate keys/IDs, YAML aliases, invalid versions,
unknown phase/requirement fields and empty required content are rejected.

Jev evaluates one batch of requirements after a user response, after all tools in
a round finish, and after a completed assistant cycle. No streaming-chunk or
individual tool-result checks are added. All requirements must be met. Unsure,
low-confidence and failed decisions retain the phase. An outstanding question
keeps the assistant waiting for the user. Confirmation must come from actual
user input. Semantic gates never grant execution permissions.

A phase change refreshes the current prompt and reselects eligible existing tools,
including workflow tools; it does not execute workflows or grant access. The
prompt includes Project base/global instructions, current-phase instructions and
requirements, and only the IDs/titles of previous and upcoming phases. Explicit
requests may return to a previous phase; a same-turn guard prevents bouncing
forward immediately after returning. Finishing the final phase keeps focus active
for follow-ups and later return requests.

Clarification phases instruct the assistant to ask at least five questions by
default, one question per round with examples and a recommendation, waiting for
the reply and considering research before the next question. Users can skip
remaining questions or request all questions together. There is no runtime
minimum-question counter, requirement type or enforcement. Unknown context must
be stated when proceeding early.

Phase run IDs, definition revisions, versions and bounded transition receipts
are stored in client-encrypted `encrypted_focus_phase_state`, separately from
`encrypted_active_focus_id`. Inference receives decrypted state only transiently.
Short-lived Redis state uses compare-and-set against the loaded snapshot, rejecting
late/duplicate transitions; activation/deactivation invalidate the corresponding
runtime. Persisted history is display data, never current-state authority.

Web and Apple detail pages show phase instructions and requirements. Active chat
focus chrome stays as it is. Phase changes are persisted system messages with a
clickable phase title linking to the catalog focus or Project detail page. Receipt
UUIDs identify the same historical event across clients and replay.

Career insights pilots Understand your situation → Confirm your career profile →
Explore career directions → Plan your next steps. The user may skip intake or
profile confirmation explicitly; the assistant keeps assumptions visible.

Implementation is deployed to dev. The focused backend suite has 80 passing
checks, including 29 phase cases and six processor transition regressions.
Isolated CI passes two CLI transport tests, three phase component tests and four
settings browser tests. Real multi-message CLI/web inference has not run because
configured disposable dev credentials are rejected; current credentials are
required. Native build/test execution is also unavailable: the remote helper
rejects build/test operations and existing workflows have no macOS runner. The
Plan remains implementing; source inspection does not establish native proof.
