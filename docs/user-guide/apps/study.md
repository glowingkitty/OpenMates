---
status: active
doc_type: guide
audience:
  - end-users
last_verified: 2026-10-05
claims:
  - id: user-guide-apps-study-source
    type: unit
    claim: The Study app guide is grounded in the Study app metadata.
    file: scripts/tests/test_user_guide_app_docs_claims.py
    assertion: user-guide-apps-study-source
---

# Study

> Track learning goals and save educational preferences.

## What It Does

The Study app helps you manage your learning journey. It stores your educational goals and background so your mate can provide personalised study help.

**Memories (available):**

- **Learning Goals** -- Save topics you want to learn more about. Difficulty and target dates are optional.

**Focus modes:**

- **What to Study** -- Helps you discover your ideal degree or field of study through guided questioning.
- **Learn Topic** -- Check what you know, build understanding, practise with hints, try an independent check, and review.
- **Test Knowledge** -- Agree on the scope, answer questions, check gaps, and review what your own answers demonstrate.
- **Socratic Questioning** -- Explores topics through thought-provoking questions to develop critical thinking.

## How to Use It

- Track a goal: "I want to learn machine learning at an intermediate level by December"
- Ask for study help: "Help me understand quantum computing"
- Test yourself: "Quiz me on European history"

## Tips

- Save your learning goals so your mate can track your progress over time.
- Your mate can help with any learning topic even without saved goals.
- You can skip a check; the assistant should then treat that part as unassessed.
- In a Wikipedia article, choose a suggested question to continue the same chat, or save the topic to your learning goals. Saving a goal does not grant new permission to share memories.
- Learning Mode also applies to follow-up suggestions, so they should guide your attempt without revealing a pending answer.

## Related

- [Code](./code.md) -- Programming documentation and code help
- [Web](./web.md) -- Research topics on the web
- [Books](./books.md) -- Track books related to your studies
