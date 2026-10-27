# Saved Preference Ranking Parser

`fetch_lmarena_rankings.py` retains offline parsing, validation, and formatting
for existing local ranking tables. Live collection is unavailable.

`parse_lmarena_markdown(markdown, category)` accepts saved table text and returns
model records with scores, vote counts, ranks, and organizations where present.
`validate_rankings(rankings, category, markdown)` reports structural and data-quality
checks on those records. `print_rankings(data, as_json)` formats an existing result.

For example, when `saved_markdown` already contains local table text:

```python
from backend.scripts.fetch_lmarena_rankings import parse_lmarena_markdown, validate_rankings

rankings = parse_lmarena_markdown(saved_markdown, category="text")
validation = validate_rankings(rankings, category="text", markdown=saved_markdown)
```

The parser preserves model names and source identifiers from saved records.
Its category values describe the input snapshot; they do not request a current
leaderboard. `fetch_lmarena_rankings` reports that no supported data source is
configured. Daily and startup refreshes are disabled, and queued refresh jobs
report unavailable. Stored results retain their original timestamps.
