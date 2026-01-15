# LMArena Leaderboard Fetcher

Fetches AI model rankings from [LMArena.ai](https://lmarena.ai/leaderboard) (formerly LMSYS Chatbot Arena).

## ⚠️ Important Notes

**LMArena has NO official API.** This script uses Firecrawl to render the JavaScript-heavy page and extract leaderboard data. The site has:
- Cloudflare protection with reCAPTCHA
- Server-side rendering with client-side hydration
- Dynamic table updates

**Requires Firecrawl API key** (configured in Vault).

## Quick Start

Run inside Docker (uses Vault API key):
```bash
docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py
docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py --category coding
docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py -o /app/lmarena.json
```

## Available Categories

### Main Categories
- `text` - Overall text leaderboard (default)
- `webdev` - Web development coding
- `vision` - Vision/multimodal models
- `text-to-image` - Image generation
- `image-edit` - Image editing
- `search` - Web search with grounding
- `text-to-video` - Video generation
- `image-to-video` - Video from image

### Text Subcategories
- `overall` - Overall text (same as `text`)
- `hard-prompts` - Challenging prompts
- `coding` - Code generation
- `math` - Mathematical reasoning
- `creative-writing` - Creative writing
- `instruction-following` - Following instructions
- `longer-query` - Longer context queries

### Aliases
- `code` → `coding`
- `writing` → `creative-writing`
- `video` → `text-to-video`
- `image` → `text-to-image`

List all categories:
```bash
docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py --list-categories
```

## Example Output

### Console Output
```
═══════════════════════════════════════════════════════════════════════════
📊 LMARENA LEADERBOARD
═══════════════════════════════════════════════════════════════════════════
Source:   https://lmarena.ai/leaderboard/text/overall
Category: text
Models:   50
Status:   ✅ Valid
Time:     2026-01-14T15:30:00+00:00

───────────────────────────────────────────────────────────────────────────
#    Model                                    Score    Votes        Org            
───────────────────────────────────────────────────────────────────────────
1    gemini-3-pro                             1489     26,385       Google         
2    grok-4.1-thinking                        1477     26,505       xAI            
3    gemini-3-flash                           1471     11,599       Google         
4    claude-opus-4-5-20251101-thinking-32k    1468     18,518       Anthropic      
5    claude-opus-4-5-20251101                 1467     19,770       Anthropic      
6    grok-4.1                                 1466     30,490       xAI            
7    gemini-3-flash (thinking-minimal)        1464     5,530        Google         
8    gpt-5.1-high                             1460     23,068       OpenAI         
9    claude-sonnet-4-5-20250929-thinking-32k  1452     37,043       Anthropic      
10   gemini-2.5-pro                           1450     86,296       Google         
...
```

### JSON Output
```json
{
  "timestamp": "2026-01-14T15:30:00.000000+00:00",
  "source": "https://lmarena.ai/leaderboard/text/overall",
  "category": "text",
  "rankings": [
    {
      "rank": 1,
      "model": "gemini-3-pro",
      "score": 1489,
      "votes": 26385,
      "organization": "Google"
    },
    {
      "rank": 2,
      "model": "grok-4.1-thinking",
      "score": 1477,
      "votes": 26505,
      "organization": "xAI"
    }
  ],
  "model_count": 50,
  "validation": {
    "valid": true,
    "warnings": []
  }
}
```

## Validation & Break Detection

The script performs **comprehensive validation** to detect when the scraper is broken:

### Output Example
```
═══════════════════════════════════════════════════════════════════════════
📊 LMARENA LEADERBOARD
═══════════════════════════════════════════════════════════════════════════
Source:   https://lmarena.ai/leaderboard/text/overall
Category: text
Models:   100
Status:   ✅ Valid
Time:     2026-01-14T12:03:50+00:00

📈 Data Quality Metrics:
   Completeness: 100.0% have all required fields
   Votes:        99.0% have vote counts
   Orgs:         100.0% have organization
   Top Brands:   12 found (gemini, claude, gpt, grok)
   Score Range:  1354-1489
   Unique Orgs:  17
```

### Validation Checks

**Phase 1: Raw Markdown Structure**
- ✅ Markdown not empty (> 1000 chars)
- ✅ Contains table separators (`| --- |`)
- ✅ Has table rows with rank numbers
- ✅ Expected column headers present
- ✅ No Cloudflare block page indicators

**Phase 2: Data Presence**
- ✅ Rankings extracted (not empty)
- ✅ At least 10 models returned

**Phase 3: Data Structure**
- ✅ All entries have required fields (rank, model, score)
- ✅ >90% have optional fields (votes, organization)
- ✅ No malformed entries

**Phase 4: Value Validation**
- ✅ Scores in valid Elo range (800-1700)
- ✅ Score spread is reasonable (> 50 points)
- ✅ Vote counts are realistic (top models have 10K+)
- ✅ Ranks are continuous (no big gaps)

**Phase 5: Content Validation**
- ✅ Expected model families found (Claude, GPT, Gemini, etc.)
- ✅ Multiple organizations present (> 3)
- ✅ Top 5 models have valid structure and scores > 1300

**Phase 6: Category-Specific**
- ✅ For text category: flagship models in top 20

### JSON Validation Output
```json
{
  "validation": {
    "valid": true,
    "warnings": [],
    "metrics": {
      "markdown_length": 57179,
      "model_count": 100,
      "completeness_pct": 100.0,
      "votes_pct": 99.0,
      "org_pct": 100.0,
      "score_min": 1354,
      "score_max": 1489,
      "expected_models_found": 12,
      "unique_orgs": 17
    }
  }
}
```

### Critical vs Non-Critical Warnings

**Critical (marks as invalid):**
- `NO_DATA` - No rankings extracted
- `NO_EXPECTED_MODELS` - Parser broken
- `CLOUDFLARE_DETECTED` - Blocked by protection
- `EMPTY_MARKDOWN` - No content received
- `NO_TABLE_SEPARATOR` - Wrong page structure

**Non-Critical (allows up to 2):**
- `MODERATE_COUNT` - Fewer models than expected
- `LOW_VOTES` - Vote counts low
- `RANK_GAPS` - Gaps in ranking sequence

### When Scraper Breaks
```
🚨 CRITICAL WARNINGS (1) - Scraper likely broken:
   ❌ NO_EXPECTED_MODELS: None of the expected models found (Claude, GPT, Gemini, etc.) - parser likely broken

⚠️  Warnings (1):
   - MISSING_HEADERS: Only 2/4 expected column headers found
```

### Monitoring
```bash
# Check if scraper is working
docker exec api python /app/backend/scripts/fetch_lmarena_rankings.py --json | jq '.validation.valid'
# Returns: true or false

# Get validation metrics
docker exec api python /app/backend/scripts/fetch_lmarena_rankings.py --json | jq '.validation.metrics'

# Check for warnings
docker exec api python /app/backend/scripts/fetch_lmarena_rankings.py --json | jq '.validation.warnings'
```

## Why It Can Break

| Issue | Cause | Solution |
|-------|-------|----------|
| **Cloudflare block** | Too many requests or bot detection | Wait and retry, use different IP |
| **Page structure changed** | LMArena updated their UI | Update parsing patterns |
| **Firecrawl timeout** | Page too slow to render | Increase timeout in Firecrawl |
| **API key issues** | Invalid or expired key | Check Vault configuration |

## Comparison with OpenRouter Rankings

| Feature | LMArena | OpenRouter |
|---------|---------|------------|
| **Data** | Human preference votes (Elo ratings) | Actual API usage (tokens) |
| **Updates** | Near real-time (votes) | Weekly/daily |
| **Categories** | Text, Vision, Video, Search, etc. | Programming, Legal, Languages |
| **API** | None (scraping required) | None (scraping required) |
| **Difficulty** | High (Cloudflare + JS) | Medium (JS rendering) |

## Data Source

Data comes from [LMArena Chatbot Arena](https://lmarena.ai):
- Rankings based on 1.5M+ human preference votes
- Uses Elo rating system (like chess rankings)
- Anonymous blind comparisons between models
- Powered by LMSYS research team (UC Berkeley)

For more details, see their [research paper](https://arxiv.org/abs/2403.04132).

## Related Scripts

- `fetch_openrouter_rankings.py` - Fetches OpenRouter API usage rankings
