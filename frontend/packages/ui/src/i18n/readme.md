
# Adding a New Language

This guide explains how to add support for a new language in the OpenMates UI.

## Steps

### 1. Create Language File
Create a new JSON file in `frontend/packages/ui/src/i18n/locales/` with the language code as the filename.

Example for French (`fr.json`):
```json
{
    "footer": {
        "language_selector": {
            "label": {
                "text": "Sélectionner la langue",
                "en_original": "Select language",
                "context": "Label for language selector"
            }
        }
        // ... add all translations
    }
}
```

### 2. Update Types
In `frontend/packages/ui/src/i18n/types.ts`, add the new language code:

```typescript
export const SUPPORTED_LOCALES = ['en', 'de', 'ja', 'es', 'cn', 'fr'] as const;
```

### 3. Update Footer Component
In `frontend/packages/ui/src/components/Footer.svelte`, add the new language to the `supportedLanguages` array:

```typescript
const supportedLanguages: Language[] = [
    { code: 'en', name: 'English' },
    { code: 'de', name: 'Deutsch' },
    { code: 'ja', name: '日本語' },
    { code: 'es', name: 'Español' },
    { code: 'cn', name: '中文' },
    { code: 'fr', name: 'Français' }
];
```

## Translation Guidelines

1. Always include the `en_original` field for reference
2. Always include the `context` field to help translators understand usage
3. Maintain the same structure as the English (`en.json`) file
4. Test the new language thoroughly in the UI

## Testing

After adding a new language:
1. Verify language appears in the footer dropdown
2. Test language switching
3. Verify all translations are displayed correctly
4. Check meta tags update properly

