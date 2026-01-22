# OpenMates™ Trademark Implementation Plan

## Overview
Strategic implementation of OpenMates™ trademark symbol in customer-facing and legal contexts while preserving clean technical code.

## Context
- Total mentions of "OpenMates" in codebase: ~841
- Existing `replaceOpenMates` action for frontend styling
- Need to balance legal protection with code maintainability

## Implementation Strategy

### Phase 1: Legal & Compliance Documents
**Priority: High**

#### Files to Update:
1. `shared/docs/privacy_policy.yml`
   - First mention: Line 71, 139

2. `frontend/packages/ui/src/i18n/locales/en.json` (Terms & Conditions section)
   - First mention in each legal section

3. `frontend/packages/ui/src/i18n/locales/de.json` (German translations)
   - Mirror English changes

**Pattern:** First mention per document section gets ™, subsequent mentions remain plain

### Phase 2: Marketing & Public-Facing Content
**Priority: High**

#### Files to Update:
1. `README.md`
   - Title (Line 1): "# OpenMates™"
   - First paragraph mention (Line 7)

2. `frontend/apps/website/static/manifest.json`
   - name: "OpenMates™"
   - short_name: Keep as "OpenMates" (space constraints)

3. `frontend/packages/ui/src/config/meta.ts`
   - siteName: "OpenMates™"
   - First occurrences in metadata

4. `frontend/apps/website/src/app.html`
   - apple-mobile-web-app-title: "OpenMates™"

### Phase 3: Business Plan Documents
**Priority: Medium**

#### Files to Update:
1. `docs/business_plan/README.md`
   - Title (Line 1): "# OpenMates™ Business Plan"

2. `docs/business_plan/01-executive-summary.md`
   - First mention only

3. `docs/business_plan/02-company-overview.md` through `12-risk-analysis.md`
   - First mention in each document

**Pattern:** First mention per document gets ™

### Phase 4: Frontend Branding
**Priority: Low**

#### Update Styling System:
1. Review `frontend/packages/ui/src/actions/replaceText.ts`
   - Consider if `replaceOpenMates` should add ™ symbol
   - Decision: Keep separate - let code handle ™ explicitly where needed

2. Translation files
   - Update translation helper in `frontend/packages/ui/src/i18n/setup.ts`
   - Consider pattern for trademark in translations

## What NOT to Update

### Technical Code (Keep Plain)
- `CLAUDE.md` - Internal agent instructions
- `package.json` descriptions
- `cleanup-db.sh` and other scripts
- GitHub URLs and paths
- Code comments
- Config files (`openmates-config.yml`)
- Service worker comments
- Internal documentation

### Repeated Mentions
- After first trademark use in same document
- UI text in conversations/chats
- Error messages
- Log messages

## Implementation Rules

### Rule 1: First Mention
First mention of OpenMates in any customer-facing or legal document should use ™

### Rule 2: Technical Contexts
No ™ in technical/internal contexts (code, configs, scripts)

### Rule 3: Space Constraints
Can omit ™ where space is critical (short_name fields, mobile contexts)

### Rule 4: Translations
Mirror English trademark usage in all language translations

## Verification Checklist

After implementation:
- [ ] Legal documents have ™ on first mention
- [ ] README.md title and first mention updated
- [ ] Meta tags and manifest updated
- [ ] Business plan documents updated
- [ ] Technical code remains unchanged
- [ ] All language translations consistent
- [ ] No broken references or links
- [ ] Visual appearance acceptable in UI

## Estimated Changes
- ~50 strategic updates (vs. 841 total mentions)
- ~15 files affected
- Minimal risk of breaking changes

## Timeline
- Phase 1 (Legal): 1 hour
- Phase 2 (Marketing): 30 minutes
- Phase 3 (Business): 45 minutes
- Phase 4 (Review): 30 minutes
- **Total**: ~3 hours

## Notes
- Preserve existing `replaceOpenMates` action for styling (bold/mark/color)
- ™ symbol is separate concern from visual styling
- Consider creating a style guide for future trademark usage
