---
status: active
doc_type: guide
audience:
  - end-users
last_verified: 2026-06-11
claims:
  - id: user-guide-apps-focus-modes-source
    type: unit
    claim: The Focus Modes guide is grounded in app/focus-mode source files.
    file: scripts/tests/test_user_guide_app_docs_claims.py
    assertion: user-guide-apps-focus-modes-source
---

# Focus Modes

> Specialised conversation modes that help your mate focus on one specific task.

## What Are Focus Modes?

Focus modes change how your mate thinks and responds for a particular type of task. When a focus mode is active, your mate becomes a specialist -- whether that is a career advisor, a video analyst, or a research assistant.

Think of it as switching your mate into a dedicated mode optimised for the job at hand.

**Examples of active focus modes:**

- **Career Insights** (Jobs app) -- Your mate becomes a thoughtful career advisor
- **Analyse Video** (Videos app) -- Your mate summarises, fact-checks, and analyses bias in YouTube videos
- **Research** (Web app, in development) -- Your mate conducts deep multi-angle research on complex topics

## How to Activate a Focus Mode

### Let Your Mate Decide

Just describe what you need and your mate will automatically activate the right focus mode:

- "I am feeling stuck in my career" -- activates Career Insights
- "Analyse this YouTube video for me" -- activates Analyse Video
- "Help me research this topic in depth" -- activates Research

When your mate activates a focus mode, you will see a brief countdown card in the chat. During the 4-second countdown, you can click the card or press Escape to cancel the activation.

### Deactivate a Focus Mode

- Right-click (or long-press on mobile) the focus mode card and select "Deactivate"
- Ask your mate: "Turn off the focus mode"
- Start a new chat -- focus modes do not carry over

## Focus Modes with Phases

Some modes organize your conversation into phases. Career insights starts by
understanding your situation, asks you to confirm your career profile, explores
possible directions, and then helps you plan a low-risk next step.

Open the focus mode's detail page to see each phase and its requirements. The
active chat keeps the same focus mode display. When a phase changes, a system
message records it; click the phase title to open the details.

The mate normally asks at least five clarifying questions, one per round, with
examples and a recommendation. It waits for your answer and can research before
asking the next question. You control the pace: ask “Skip the remaining questions
and proceed with what you know” or “Ask all remaining questions at once.”
Confirmation phases wait for your approval or an explicit request to proceed on
assumptions. You can ask to return to an earlier phase, for example, “Return to
Understand your situation so we can revisit my preferences.”

## Focus Modes vs Skills

- **Focus modes** change how your mate thinks and responds (its personality and approach)
- **Skills** are actions your mate performs (searching, generating, reading)

Focus modes often use skills as part of their work. For example, the Analyse Video mode uses the transcript skill to get the video text and the web search skill to fact-check claims.

## Tips

- Focus modes only affect the current conversation. Starting a new chat resets everything.
- You can see which focus modes each app offers in the Apps.
- Some focus modes are listed as "planned" in the Apps -- these are not yet available.

## Related

- [Skills](./skills.md) -- The actions your mates can perform
- [Apps](./app-store.md) -- Browse all available focus modes
