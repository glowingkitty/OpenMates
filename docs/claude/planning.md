# Implementation Planning

Before writing any code for a non-trivial task, you MUST create a structured implementation plan. This prevents wasted effort from misunderstood requirements, missed dependencies, and architectural mistakes.

---

## When to Plan

- **Always plan** for new features, significant refactors, or multi-file changes
- **Skip planning** only for single-line fixes, typo corrections, or trivial changes where the path is obvious

---

## Planning Steps

### 1. Define Scope

State clearly what is in scope and what is NOT:

- **In scope:** What this task will accomplish
- **Out of scope:** Related work that will NOT be done now (prevents scope creep)
- **Dependencies:** Other systems, services, or files this change touches

### 2. List Affected Files and Components

Before writing any code, identify every file and component that will be created, modified, or deleted. This catches dependency surprises early rather than mid-implementation.

### 3. State Assumptions

Write out every assumption you are making. If any assumption is wrong, the implementation could be wrong. Examples:

- "I assume the user object always has an `email` field at this point"
- "I assume the API endpoint already validates the token before this handler runs"
- "I assume this component only renders when `isLoggedIn` is true"

If you are unsure about an assumption, **ask the user or verify in the code** before proceeding.

### 4. Include a Step-by-Step Processing Example (CRITICAL)

**You MUST include at least one concrete, natural-language walkthrough** showing how data flows through the system for a realistic scenario. This is the single most effective way to catch misunderstandings before they become bugs.

Write it as a numbered sequence describing what happens at each step — from trigger to final result. Include actual example values, not abstract placeholders.

**Example format:**

> **Scenario: User submits a new message in a group chat**
>
> 1. User types "Hello everyone" and clicks Send
> 2. Frontend calls `POST /v1/chats/{chat_id}/messages` with body `{ "content": "Hello everyone" }`
> 3. API handler validates the user is a member of `chat_id`
> 4. Handler creates a new `Message` record in the database with `status: "sent"`
> 5. Handler publishes a `new_message` event to the WebSocket channel for `chat_id`
> 6. All connected members receive the WebSocket event and their UI appends the message
> 7. API returns `201` with the created message object to the sender

**Why this matters:**

- Forces you to think through the actual flow, not just the happy path
- Reveals missing steps (e.g., "wait, where does permission checking happen?")
- Surfaces data shape mismatches early (e.g., "the frontend sends `content` but the backend expects `text`")
- Makes it easy for the user to spot misunderstandings before any code is written

For complex features, include multiple scenarios (happy path, error case, edge case).

### 5. Define "Done" Criteria

State explicitly what success looks like and how to verify it:

- What behavior should be observable when this is complete?
- What specific test or check proves it works?
- Are there UI states, API responses, or log outputs to verify?

### 6. Suggest E2E Test Specs

**Propose concrete end-to-end test descriptions** that would verify the feature works correctly. Write them as `spec.ts`-style test names — descriptive enough that the user can evaluate whether each test is worth implementing.

Do NOT write the test code during planning. Just list the test descriptions. The user decides which ones to implement after reviewing the plan.

**Example format:**

> **Suggested E2E Tests:**
>
> - `should display new message in chat for all connected members`
> - `should show error toast when sending message to a chat the user is not a member of`
> - `should persist message after page reload`
> - `should show sending indicator while message is in transit`

**Why this matters:**

- Forces thinking about testability during design, not after implementation
- Catches untestable designs early — if you can't describe a test, the scope may be unclear
- Test descriptions double as acceptance criteria
- Gives the user control over test investment — they pick which tests matter

**Guidelines:**

- Cover the happy path, at least one error case, and any critical edge cases
- Write test names in plain language (`should ...` format)
- Group by feature area if there are many tests
- Keep the list focused — 3-8 tests per feature, not 30

### 7. Flag Risks and Unknowns

List anything that could block progress, cause regressions, or require rework:

- Parts of the codebase you haven't inspected yet
- Potential conflicts with concurrent work by other assistants
- Performance concerns
- Edge cases you're aware of but not handling yet

---

## Plan Format

Use this template for your plan. Keep it concise — bullet points, not essays.

```
## Implementation Plan

**Task:** <one-line summary>

**Scope:**
- In: <what will be done>
- Out: <what will NOT be done>

**Affected Files:**
- `path/to/file.ts` — <what changes>
- `path/to/other.py` — <what changes>

**Assumptions:**
- <assumption 1>
- <assumption 2>

**Processing Example:**
> Scenario: <realistic scenario name>
> 1. <step 1 with example values>
> 2. <step 2>
> ...

**Done When:**
- <criterion 1>
- <criterion 2>

**Suggested E2E Tests:**
- `should <test description 1>`
- `should <test description 2>`
- `should <error case description>`

**Risks:**
- <risk 1>
- <risk 2>
```

---

## Common Planning Mistakes to Avoid

- **Jumping straight to code** — Always plan first for non-trivial work
- **Vague scope** — "Improve the chat" is not a plan. Be specific about what changes
- **Missing the processing example** — This is the most important part. Do not skip it
- **Assuming you know the codebase** — Verify by reading actual files, not from memory
- **Ignoring concurrent work** — Other assistants may be changing the same files. Check git status
- **Planning too much** — The plan should take 2-5 minutes, not 30. If you're writing an essay, simplify
