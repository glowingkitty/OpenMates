---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/i18n/sources/
  - frontend/packages/ui/scripts/build-translations.js
  - frontend/packages/ui/package.json
---

# Translations (i18n)

> YAML source files are the single source of truth for all 25 supported languages. A build step converts them to JSON locale files consumed at runtime.

## Why This Exists

YAML provides better readability, multi-line support, and translator context fields compared to raw JSON. The build step ensures consistent output and catches formatting errors early.

## How It Works

### Source Files

Location: `frontend/packages/ui/src/i18n/sources/`

```
sources/
  email/
    main.yml
  login/
    main.yml
  settings/
    main.yml
    account.yml
    app_store.yml
    billing.yml
    interface.yml
    security.yml
    ...
  signup/
    main.yml
```

Files in subdirectories contribute to the parent namespace (e.g., `settings/app_store.yml` -> `settings.app_store.*`). Large files (>500 lines) are automatically split by top-level key prefix.

### YAML Format

```yaml
confirm_email:
  context: "Email subject for email confirmation"
  en: "Confirm your email address"
  de: "Bestaetige deine E-Mail Adresse"
  fr: ""
```

Rules: `en` first, then `de`, then alphabetical. Empty `""` for missing translations. `context` field for translator guidance (stripped from JSON output). Multi-line text uses YAML literal block scalars (`|`).

### Build Process

```bash
cd frontend/packages/ui && npm run prepare
```

The `prepare` script runs 8 steps in sequence: `build:translations`, `validate:locales`, `generate-apps-metadata`, `generate-embed-registry`, `generate-models-metadata`, `generate-providers-metadata`, `generate-icon-urls`, `validate:icon-refs`.

`build:translations` specifically: recursively loads all YAML from `sources/`, merges by namespace, strips `context` fields, preserves newlines as `\n`, generates JSON for all 25 languages.

### Generated Files

Output: `frontend/packages/ui/src/i18n/locales/` (gitignored, never edit directly).

### Usage in Code

**Frontend (Svelte/TypeScript):**
```typescript
import { text } from '@repo/ui';
const msg = $text('email.confirm_email.text');
```

**Backend (Python):**
```python
from backend.core.api.app.services.translations import TranslationService
text = TranslationService().get_nested_translation("email.confirm_email.text", "en", {})
```

Always append `.text` when accessing -- the JSON structure wraps each value in a `text` field.

### Supported Languages (21)

**European:** en, de, es, fr, it, pt, nl, pl, cs, sv, tr, ru
**Asian:** ja, zh, ko, hi, th, vi, id, ar, he

## Edge Cases

- Missing key at runtime: check YAML source exists, re-run `npm run prepare`, verify key path (case-sensitive).
- Translation not updating: re-run build, clear browser cache.
- CRITICAL: Never edit the `.json` files in `locales/` directly. Always edit `.yml` sources and rebuild.

## Related Docs

- [i18n Guide](../../contributing/guides/i18n.md) -- contributor workflow for adding translations
