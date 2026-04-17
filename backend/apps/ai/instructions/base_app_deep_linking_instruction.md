**App Deep Linking:** When referencing available apps in your responses, link to them using relative hash-based deep links. Format: `[link text](/#settings/apps/{app_id})`. Examples:
- `[set a reminder](/#settings/apps/reminder)`
- `[create a document](/#settings/apps/docs)`
- `[web search settings](/#settings/apps/web)`
NEVER use absolute URLs like `https://openmates.org/apps/...` — these pages do not exist. Always use the relative `/#settings/apps/{app_id}` format.
