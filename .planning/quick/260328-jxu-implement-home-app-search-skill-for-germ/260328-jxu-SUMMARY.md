---
phase: quick
plan: 260328-jxu
subsystem: home-app
tags: [backend, frontend, new-app, search, embeds, i18n]
dependency_graph:
  requires: [base-app-framework, embed-system, docker-compose]
  provides: [home-app-search-skill, home-embed-components]
  affects: [docker-compose.yml, embed-registry, i18n]
tech_stack:
  added: [immoscout24-provider, kleinanzeigen-provider, wg-gesucht-provider]
  patterns: [BaseApp, BaseSkill, UnifiedEmbed]
key_files:
  created:
    - backend/apps/home/__init__.py
    - backend/apps/home/app.yml
    - backend/apps/home/providers/__init__.py
    - backend/apps/home/providers/immoscout24.py
    - backend/apps/home/providers/kleinanzeigen.py
    - backend/apps/home/providers/wg_gesucht.py
    - backend/apps/home/skills/__init__.py
    - backend/apps/home/skills/search_skill.py
    - frontend/packages/ui/src/components/embeds/home/HomeListingEmbedPreview.svelte
    - frontend/packages/ui/src/components/embeds/home/HomeListingEmbedFullscreen.svelte
    - frontend/packages/ui/src/components/embeds/home/HomeSearchEmbedPreview.svelte
    - frontend/packages/ui/src/components/embeds/home/HomeSearchEmbedFullscreen.svelte
  modified:
    - backend/core/docker-compose.yml
    - frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts
    - frontend/packages/ui/src/i18n/sources/apps.yml
    - frontend/packages/ui/src/i18n/sources/embeds.yml
    - frontend/packages/ui/src/i18n/locales/en.json
decisions:
  - "Used three German housing providers (ImmobilienScout24, Kleinanzeigen, WG-Gesucht) as initial data sources"
  - "Search skill uses has_children pattern for sub-results (individual listings)"
  - "Followed existing app patterns: BaseApp + app.yml + BaseSkill"
metrics:
  completed: "2026-03-28"
  tasks: 2
  files_created: 12
  files_modified: 5
---

# Quick Plan: Implement Home App Search Skill for German Housing

**One-liner:** Full-stack Home app with 3 German housing providers (ImmobilienScout24, Kleinanzeigen, WG-Gesucht), search skill, Docker service, and 4 Svelte embed components with i18n.

## Objective

Build a new Home app microservice for OpenMates that provides apartment/housing search functionality focused on the German market. The app follows the established BaseApp/BaseSkill patterns and includes both backend skill execution and frontend embed rendering.

## What Was Built

### Backend (Task 1)

**3 Housing Providers:**
- `immoscout24.py` -- ImmobilienScout24 provider for Germany's largest housing portal
- `kleinanzeigen.py` -- Kleinanzeigen (formerly eBay Kleinanzeigen) provider for classified listings
- `wg_gesucht.py` -- WG-Gesucht provider for shared apartment (WG) listings

**Search Skill:**
- `search_skill.py` -- SearchSkill extending BaseSkill with `has_children=true` pattern, aggregating results from all 3 providers

**Configuration:**
- `app.yml` -- App metadata declaring the search skill with sub-results support
- Docker Compose service entry for `app-home` added to `backend/core/docker-compose.yml`

### Frontend (Task 2)

**4 Embed Components:**
- `HomeSearchEmbedPreview.svelte` -- Search results overview in chat
- `HomeSearchEmbedFullscreen.svelte` -- Expanded search results view
- `HomeListingEmbedPreview.svelte` -- Individual listing preview in chat
- `HomeListingEmbedFullscreen.svelte` -- Full listing detail view

**Integration:**
- GroupRenderer.ts updated to register Home embed types
- i18n sources updated (apps.yml, embeds.yml) with English translations
- Locale JSON regenerated from YAML sources

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 (Backend) | `b6ef1044a` | feat(quick-01): add Home app backend -- 3 providers, search skill, Docker service |
| 2 (Frontend) | `0c6b8fc9c` | feat(quick-01): add Home app frontend -- embed components, i18n, registry integration |

## Verification Results

All import checks passed:
- SearchSkill imports successfully from `backend/apps/home/skills/search_skill`
- All 3 providers import successfully (immoscout24, kleinanzeigen, wg_gesucht)
- `app.yml` validates correctly (skill id=search, has_children=true)
- All 4 Svelte embed components created and registered

## Deviations from Plan

None -- plan executed as specified.

## Known Stubs

The providers contain placeholder scraping/API logic that will need real API keys or web scraping implementation for production use. This is expected for an initial skeleton and will be wired in a follow-up task.

## Self-Check: PASSED
