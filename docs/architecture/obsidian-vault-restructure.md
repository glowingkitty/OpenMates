# Obsidian Vault Restructure Plan

Status: PROPOSAL — awaiting review before implementation.

---

## Current State

- ~224 files, ~120 are auto-generated test spec notes (removing)
- ~100 real notes: tasks, features, bugs, marketing, research, daily notes, loose ideas
- 12 orphan files at vault root (sentence-named ideas with no folder)
- Good foundations: frontmatter schema, templates, daily note automation, Kanban boards, dashboard
- Problems: flat root, overlapping categories, no clear separation between knowledge and tasks

## Design Principles

1. **Karpathy's 3 layers**: Schema (rules for agents) / Wiki (living knowledge) / Raw (immutable sources)
2. **PARA-lite**: Projects (time-bound) / Areas (ongoing) / Resources (reference) / Archive
3. **Tasks plugin as Linear replacement**: emoji syntax for dates/priority, custom statuses, query dashboards
4. **AI-agent friendly**: consistent frontmatter, `_schema.md` governs agent behavior, `_index.md` per section

---

## New Vault Structure

```
memory/
|
|-- _schema.md                      # Agent interaction rules (Karpathy's schema layer)
|-- _index.md                       # Vault table of contents (auto-maintained by agents)
|-- Dashboard.md                    # Master task dashboard (Dataview + Tasks queries)
|
|-- Daily/
|   |-- 2026-05-01.md
|   |-- ...
|
|-- Projects/                       # Time-bound initiatives with clear end states
|   |-- _index.md                   # MOC: all projects with status
|   |-- hackernews-launch.md        # was: hackernews announcement/
|   |-- obsidian-plugin.md          # was: build custom obsidian plugin.md
|   |-- obsidian-workflow.md        # was: Obsidian workflow improvements.md
|   |-- cronjob-automation.md       # was: Implement regular cronjob/
|   |-- user-growth-strategy.md     # was: brainstorm how to increase user growth.md
|   |-- linear-to-obsidian.md       # NEW: this migration itself
|
|-- Areas/                          # Ongoing responsibilities, no end date
|   |-- engineering/
|   |   |-- _overview.md            # Current state, tech debt, priorities
|   |   |-- bugs/                   # was: OpenMates/Bugs/
|   |   |   |-- payment-non-eu.md
|   |   |   |-- chat-screen-stuck.md
|   |   |   |-- urgent-bugs.md
|   |   |-- features/               # was: OpenMates/Features/
|   |   |   |-- code-generation-designs.md
|   |   |   |-- safety-tests.md
|   |   |   |-- permission-management.md
|   |   |   |-- knowledge-settings.md
|   |   |   |-- reward-system.md
|   |   |   |-- ...
|   |   |-- tests/
|   |       |-- overview.md         # was: Test runs.md (keep summary, remove 120 spec files)
|   |
|   |-- product/
|   |   |-- _overview.md
|   |   |-- agentic-coding.md       # was: Agentic coding improvements.md
|   |   |-- ai-auto-process.md      # was: Let AI model auto process notes.md
|   |   |-- web-search-in-queries.md # was: Should we include news or web search...md
|   |   |-- ask-permission-flow.md  # was: Ask for permission flow.md
|   |
|   |-- marketing/
|   |   |-- _overview.md
|   |   |-- automations.md          # was: Marketing Automations.md
|   |   |-- communication-style.md
|   |   |-- seo-monitoring.md       # was: Auto check SEO...md
|   |   |-- social-monitoring.md    # was: Check the web people making posts...md
|   |   |-- competitor-watch.md     # was: Check what other ai companies...md
|   |   |-- content-schedule.md     # was: Auto create marketing schedule...md
|   |   |-- blog/                   # was: Marketing/Blog posts/
|   |   |-- events/                 # was: Marketing/Events/ + Events/
|   |   |   |-- gpn24-2026.md
|   |   |   |-- jugend-hack.md
|   |   |-- meetup-groups/          # was: Marketing/Meetup groups/
|   |   |-- videos/                 # was: Marketing/Videos/ + Videos/
|   |   |-- newsletters.md         # was: Read various newsletters...md
|   |
|   |-- finance/
|   |   |-- _overview.md            # was: Finances.md (expanded)
|   |   |-- funding-programs.md     # was: agent to check for new funding...md
|   |
|   |-- business/
|   |   |-- _overview.md
|   |   |-- profile.md              # was: OpenMates Business Profile.md
|   |   |-- steward-ownership.md    # referenced in profile
|   |
|   |-- legal/
|       |-- _overview.md
|       |-- privacy.md              # was: legal/privacy.md
|
|-- Resources/                      # Reference material, not actionable
|   |-- research/                   # was: research/
|   |-- videos/                     # was: Videos/ (reference videos, not marketing)
|   |   |-- ai-chatbots-hbo.md
|   |   |-- remotion-vs-davinci.md
|   |-- interesting-videos.md       # was: Interesting videos.md
|
|-- Archive/                        # Completed projects, outdated notes
|   |-- (empty initially, moved here when done)
|
|-- Templates/
|   |-- task.md
|   |-- bug.md
|   |-- project.md
|   |-- event.md
|   |-- daily-note.md
|   |-- decision.md                 # NEW
|   |-- area-overview.md            # NEW
|
|-- Boards/                         # Generated Kanban boards
|   |-- all-todos.md
|   |-- bugs.md
|   |-- marketing.md
|
|-- assets/                         # Images, videos, attachments
|   |-- current/
|       |-- ...
```

### Key Changes

| Before | After | Why |
|--------|-------|-----|
| 12 loose files at root | Moved to Projects/ or Areas/ | No orphans |
| `OpenMates/` top-level folder | Dissolved into Areas/ | Everything is OpenMates — redundant nesting |
| `OpenMates/Tasks/` + `OpenMates/Tasks/Boards/` | Boards/ at root, tasks live in their area | Tasks belong where the work is, not in a separate silo |
| 120 test spec files | Deleted, keep only `tests/overview.md` | Noise reduction |
| `Events/` at root + `Marketing/Events/` | `Areas/marketing/events/` | Single location |
| `Videos/` at root + `Marketing/Videos/` | Split: marketing videos vs reference videos | Clear purpose |
| `hackernews announcement/` (folder) | `Projects/hackernews-launch.md` (file) | Was a folder with ideas, becomes a project note |
| `Implement regular cronjob/` (folder) | `Projects/cronjob-automation.md` (file) | Same |
| Sentence-length filenames | kebab-case short names | AI-parseable, less clutter |

---

## Frontmatter Schema (expanded from current)

Keeping your existing schema and extending it:

```yaml
---
# Required for all notes
type: task | bug | feature | project | event | decision | guide | note | daily-note | area-overview

# Required for actionable notes
status: backlog | todo | in_progress | in_review | blocked | waiting | done | cancelled
priority: lowest | low | medium | high | highest
area: engineering | product | marketing | finance | business | legal | personal

# Dates (use whichever apply)
created: YYYY-MM-DD
due: YYYY-MM-DD          # deadline
date: YYYY-MM-DD         # event date
scheduled: YYYY-MM-DD    # when you plan to work on it

# Optional
project: string           # link to parent project if applicable
tags: []
linear_id: OPE-XX        # for migrated Linear issues (preserves traceability)
---
```

### Changes from current schema
- `task_status` renamed to `status` (shorter, standard)
- Added `blocked`, `waiting`, `cancelled` states
- Added `lowest`, `highest` priority levels
- `project: OpenMates` dropped (everything is OpenMates, redundant)
- `project:` now means "parent project note" when a task belongs to a specific initiative

---

## Task Management: Replacing Linear

### Custom Task Statuses (Tasks plugin config)

```
[ ] = TODO         (type: TODO)
[/] = IN PROGRESS  (type: IN_PROGRESS)
[x] = DONE         (type: DONE)
[-] = CANCELLED    (type: CANCELLED)
[?] = WAITING      (type: NON_TASK)  — blocked on someone else
[@] = BLOCKED      (type: NON_TASK)  — blocked on internal dependency
```

### What replaces what

| Linear feature | Obsidian replacement |
|---------------|---------------------|
| My Issues | Dashboard.md — Tasks queries filtered by `status.type is IN_PROGRESS` or `not done` |
| Issue board | Boards/all-todos.md (Kanban) — auto-generated from frontmatter |
| Backlog | Tasks query: `not done`, `no due date`, `tags do not include #someday` |
| Cycles/Sprints | Weekly focus section in Daily Notes + due date ranges in Tasks queries |
| Labels | `area:` frontmatter field + tags |
| Priority | Tasks plugin priority emojis + frontmatter `priority:` |
| Comments/discussion | Body content of the note itself |
| Issue search | Obsidian search + Dataview queries |
| Automation | `sync_obsidian_tasks.py` + `generate_obsidian_task_boards.py` (already exist) |

### Dashboard.md sections

1. **In Progress** — `status.type is IN_PROGRESS`, grouped by area
2. **Overdue** — `due before today`, sorted by priority
3. **Due Today** — `due today`
4. **Due This Week** — `due after today`, `due before in 7 days`
5. **High Priority Unscheduled** — `not done`, `priority is high`, `no due date`
6. **Waiting/Blocked** — `status.type is NON_TASK` (custom `[?]` and `[@]`)
7. **Bugs** — Dataview: `type = "bug"`, `status != "done"`
8. **Backlog by Area** — `not done`, `no due date`, grouped by area

### Migration from Linear

1. Export open Linear issues as CSV
2. Script converts each to a markdown note with frontmatter (preserving `linear_id:`)
3. Place in appropriate Area folder based on labels
4. Regenerate Kanban boards
5. Verify Dashboard.md queries pick everything up
6. Keep Linear read-only for 2 weeks as safety net, then archive

---

## Agent Interaction Protocol (_schema.md)

This file lives at the vault root and governs how Claude agents interact with the vault.
It implements Karpathy's "schema layer."

### Core rules for agents

```markdown
# Vault Schema — Agent Instructions

## Identity
This vault is the shared knowledge base for the OpenMates project.
It is co-edited by a human (Marco) and AI agents (Claude).

## Three Layers
1. **Schema** (this file) — rules agents must follow
2. **Wiki** (Areas/, Projects/, Dashboard.md) — living knowledge, actively maintained
3. **Raw** (Resources/, assets/) — reference material, rarely modified

## Operations

### INGEST (adding new information)
- New tasks/bugs/features: create note in the correct Area/ subfolder
- Use the appropriate Template (Templates/task.md, Templates/bug.md, etc.)
- Always include full frontmatter (type, status, priority, area, created)
- After creating: run sync_obsidian_tasks.py to update boards
- Log the addition in today's Daily Note under "Manual Notes"

### QUERY (answering questions)
- Search vault notes to synthesize answers
- Prefer linking to existing notes over duplicating content
- If an answer reveals a gap, create a new note to fill it

### LINT (periodic health checks)
- Check for notes missing required frontmatter fields
- Flag contradictions between notes
- Identify orphan notes (no inbound links)
- Flag stale tasks (status: in_progress for >14 days with no updates)
- Report to Daily Note or as a comment in the relevant note

## Naming Conventions
- File names: kebab-case, max 40 chars (e.g., payment-non-eu.md)
- No emojis in file names
- No sentence-length file names
- Folders: lowercase kebab-case

## Frontmatter Contract
[... the schema from above ...]

## What Agents Must NOT Do
- Delete notes without explicit human confirmation
- Modify Daily Notes outside of AUTO marker blocks
- Change note frontmatter status to "done" (only humans close tasks)
- Create notes in Templates/ or Boards/ (these are generated)
- Edit _schema.md without human approval
```

---

## Templates (updated)

### Templates/task.md
```yaml
---
type: task
status: backlog
priority: medium
area:
created: {{date:YYYY-MM-DD}}
due:
tags:
  - task
---

# {{title}}

## Goal

## Context

## Tasks

- [ ] Define next action

## Questions
```

### Templates/bug.md
```yaml
---
type: bug
status: todo
priority: high
area: engineering
created: {{date:YYYY-MM-DD}}
due:
tags:
  - bug
---

# {{title}}

## Symptom

## Steps to Reproduce

## Expected vs Actual

## Investigation

## Fix

- [ ] Identify root cause
- [ ] Fix
- [ ] Verify
```

### Templates/decision.md (NEW)
```yaml
---
type: decision
status: todo
area:
created: {{date:YYYY-MM-DD}}
tags:
  - decision
---

# {{title}}

## Context

## Options

### Option A
- Pros:
- Cons:

### Option B
- Pros:
- Cons:

## Decision

## Rationale
```

### Templates/area-overview.md (NEW)
```yaml
---
type: area-overview
area:
created: {{date:YYYY-MM-DD}}
tags:
  - overview
---

# {{title}}

## Current State

## Key Priorities

## Open Questions

## Related Projects
```

### Templates/daily-note.md (updated)
```yaml
---
type: daily-note
date: {{date:YYYY-MM-DD}}
tags:
  - daily-note
---

# {{date:YYYY-MM-DD}}

## Daily Summary

<!-- AUTO:daily-summary:start -->
No changed notes detected yet.
<!-- AUTO:daily-summary:end -->

## Server Stats

<!-- AUTO:server-stats:start -->
<!-- AUTO:server-stats:end -->

## Focus

-

## Manual Notes

-

## Recent Activity

<!-- AUTO:changed-notes:start -->
<!-- AUTO:changed-notes:end -->

## Due Today

` ` `dataview
TABLE priority, due, status, area
FROM "" AND -"Templates" AND -"Boards"
WHERE due = date(this.date) AND status != "done"
SORT priority DESC
` ` `

## Decisions

-

## Questions

-

## End Of Day Review

-
```

---

## Implementation Plan

### Phase 1: Structure (do first)
1. Create new folder structure
2. Move existing files to new locations (with renames)
3. Delete 120 test spec files, keep overview
4. Update all `[[wikilinks]]` that break from moves
5. Update board generator and daily note scripts for new paths

### Phase 2: Schema + Templates
1. Write `_schema.md` at vault root
2. Write `_index.md` at vault root
3. Update templates with new frontmatter schema
4. Backfill frontmatter on existing notes (`task_status` -> `status`, drop `project: OpenMates`)

### Phase 3: Dashboard
1. Rewrite Dashboard.md with new query sections
2. Regenerate Kanban boards for new structure
3. Verify all queries resolve correctly

### Phase 4: Linear Migration
1. Export open Linear issues
2. Convert to Obsidian notes with script
3. Place in correct Area folders
4. Verify on Dashboard + Boards
5. Keep Linear read-only for 2 weeks

### Phase 5: Claude Instructions
1. Add vault interaction rules to CLAUDE.md or `.claude/rules/obsidian.md`
2. Update `sessions.py` to surface relevant vault notes in session context
3. Define which skills/sessions can write to the vault

---

## Open Questions

- [ ] Should we keep the `raw/` folder that currently exists, or merge its contents into `Resources/`?
- [ ] Do we want weekly review notes in addition to daily notes?
- [ ] Should the Daily Note template include a WIP limit check (show in-progress count)?
- [ ] How should Claude sessions reference vault notes — by path, by wikilink, or both?
- [ ] Should we add a `personal/` Area for non-OpenMates stuff (finances, etc.)?
