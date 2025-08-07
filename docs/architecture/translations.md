# Translations architecture

## Current implementation

Currently all translations are located in @/frontend/packages/ui/src/i18n/locales as .json files, named after the language code:

- /frontend/packages/ui/src/i18n/locales/en.json
- /frontend/packages/ui/src/i18n/locales/de.json
- /frontend/packages/ui/src/i18n/locales/es.json
- etc.

### How the frontend loads translations

The frontend should use the text method to load translations. The language of the user is automatically considered to load the correct translations.

```ts
import { text } from '@repo/ui';

emailError = $text('signup.at_missing.text');
```


### How the backend loads translations

The backend should typically return simple text strings with the key of the translation text, like `signup.at_missing.text`, which should then be replaced in the frontend by the actual text in the language of the UI on the client.
Special case: when loading translations for messages which will be added to the chat history, we need to load the translations in the backend and process it just as a regular assistant response.

Loading of translations in the backend:
via @/backend/core/api/app/services/translations.py:

Example:
```python
from backend.core.api.app.services.translations import TranslationService

translation_service = TranslationService
language = 'en'
text = translation_service.get_nested_translation("email.from_unknown_location.text", language, {})

```

## Improvement plans

Managing translations should become easier and giant files should be prevented.
Solution: create folders with subfolders and .yml files for separate text types/areas.
For example:

- /translations/signup.yml
- /translations/login.yml
- /translations/payment_processing.yml
- /translations/settings/main_page.yml
- /translations/settings/interface.yml
- /translations/settings/mates.yml
- etc.

Each .yml file should then