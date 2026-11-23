# Contract: Project presentation (description, icon, category)

Plan: `docs/plans/project-presentation/plan.yml` (TASK-1807). Owning Specification:
`specifications/features/projects/specification.yml` (`projects.presentation.*`).

## 1. Stored fields (`projects` collection)

All values are encrypted with the Project key (`encrypt_text(value, project_key, [])`,
same as `encrypted_name`). The server stores and returns ciphertext only.

| Field | Plaintext |
| --- | --- |
| `encrypted_description` (existing) | one line, at most 140 characters, may be empty |
| `encrypted_icon` (existing) | Lucide icon name, kebab case (`^[a-z0-9]+(-[a-z0-9]+)*$`, at most 40 chars); `folder` is the legacy default |
| `encrypted_category` (new, nullable) | one of the categories in section 2 |
| `encrypted_presentation_state` (new, nullable) | JSON, section 3 |

Both new fields are optional in `POST /v1/projects` and `PATCH /v1/projects/{id}` and
are returned by list/show like the other encrypted fields.

## 2. Categories

`software_development, business_development, medical_health, legal_law,
maker_prototyping, marketing_sales, finance, design, electrical_engineering,
movies_tv, history, science, life_coach_psychology, cooking_food, activism,
general_knowledge`. The tile gradient is `CATEGORY_GRADIENTS[category]` from
`frontend/packages/chatCategoryTheme.ts` (the chat gradients). No category: the
Projects app gradient, as today.

## 3. Presentation state

```json
{"v": 1,
 "sources": {"description": "assistant", "icon": "user", "category": "backfill"},
 "specification_refreshed": false,
 "backfilled": true}
```

`sources.<field>` is `assistant`, `backfill` or `user`, or absent when never written.
A missing state (legacy Project) is treated as: no sources, not refreshed, not backfilled.

## 4. Write rules (Rust core, `work/projects/presentation.rs`)

Normalise every proposal first: description collapsed to one line, cut at a word
boundary to 140 chars with `…`; icon lowercased and validated (invalid: dropped);
category validated (invalid: dropped). Origins:

- `creation`: assistant-created Project. Writes every non-empty field, sources
  `assistant`, `backfilled: true`, `specification_refreshed: false`.
- `specification_approval`: no-op when `specification_refreshed` is true. Else writes
  each non-empty proposed field whose source is not `user`, sources `assistant`, then
  sets `specification_refreshed: true` (also when nothing was written).
- `backfill`: only when the state is missing and the Project has at least one item.
  Writes each non-empty proposed field whose current value is unset (description
  empty, icon empty or `folder`, category empty); a value already present (typed
  before this feature) counts as the user's. Sources `backfill`, `backfilled: true`.
  Category: the dominant chat category (section 5) wins over the proposal.
- `user`: writes exactly the fields the user changed (an empty description too),
  sources `user`. Never refused.

## 5. Dominant category (mixed Projects)

Input: the Project's chats as `(category, updated_at)`. The category most chats share
wins; a tie goes to the most recently updated chat among the tied categories; no
categorised chat: `None` (the model's proposal is used).

## 6. Assistant creation request (`openmates.project_create_request` v1, additive)

`pending_client_action` gains optional `icon` and `category` (plaintext, validated
as above; the existing `description` now carries the one-line description). Clients
that do not know them ignore them. The core encrypts them into the create payload
together with an `encrypted_presentation_state` built with origin `creation`.

## 7. Suggest route

`POST /v1/projects/presentation/suggest` — first-party session only (no API keys),
20/minute per user, no credits, stores nothing, logs no plaintext.

Request:
```json
{"purpose": "specification_approval" | "backfill",
 "name": "Recipe Keeper",
 "description": "",
 "specification": {"title": "...", "summary": "..."} | null,
 "chat_titles": ["..."],          // at most 20, each at most 200 chars
 "item_names": ["..."]}           // at most 40, each at most 200 chars
```
Response: `{"presentation": {"description": "...", "icon": "chef-hat", "category": "cooking_food"}}`.
The description may be empty when the context is too thin to describe the Project.

## 8. Web decisions (Rust-only ops of `projectDecide`)

- `projectPresentationPlan` input `{origin, state, current: {description, icon, category},
  proposal: {description, icon, category}, itemCount, chats: [{category, updatedAt}]}`
  (state is the decrypted JSON or null) answers
  `{write: bool, fields: {description?, icon?, category?}, state: {...}}`; `fields`
  holds only the values to encrypt and send, `state` is the new state JSON to encrypt.
- `projectBackfillPick` input `{projects: [{projectId, hasState, itemCount}], limit}`
  answers `{projectIds: [...]}` (state missing and itemCount > 0, list order, at most
  `limit`, default 5).
