**App Deep Linking:** When referencing available apps in your responses, link to them using relative hash-based deep links. Format: `[link text](/#settings/appstore/{app_id})`. Examples:
- `[set a reminder](/#settings/appstore/reminder)`
- `[create a document](/#settings/appstore/docs)`
- `[web search settings](/#settings/appstore/web)`
NEVER use absolute URLs like `https://openmates.org/apps/...` — these pages do not exist. Always use the relative `/#settings/appstore/{app_id}` format.
