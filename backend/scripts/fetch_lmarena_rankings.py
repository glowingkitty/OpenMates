#!/usr/bin/env python3
"""
Fetches AI model rankings from LMArena.ai using Firecrawl for JavaScript rendering.

This script:
1. Uses Firecrawl API (via Vault) to scrape the dynamically-rendered leaderboard page
2. Parses the leaderboard table (model, score, votes, organization)
3. Validates the output to detect when the scraper breaks
4. Outputs formatted text or JSON

Usage:
    docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py
    docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py --category coding
    docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py --json
    docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py -o /app/lmarena.json

Options:
    --category CAT    Category to fetch (text, webdev, coding, math, etc.)
    --json            Output as JSON instead of formatted text
    -o, --output FILE Save output to file
    --limit N         Max models to return (default: 50)
    --list-categories List all available categories

Note: This script is designed to run inside the Docker container where it has
access to Vault for the Firecrawl API key.

LMArena has NO official API - this uses Firecrawl to render JavaScript and
extract leaderboard data from the rendered page.
"""

import asyncio
import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Add the backend directory to the Python path for imports
sys.path.insert(0, '/app/backend')

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.firecrawl.firecrawl_scrape import scrape_url

# Configure logging - suppress verbose library logs
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Set our script logger to INFO
script_logger = logging.getLogger('fetch_lmarena_rankings')
script_logger.setLevel(logging.INFO)

# Suppress verbose logging from libraries
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

BASE_URL = "https://lmarena.ai"

# Available leaderboard categories and their URL paths
CATEGORIES = {
    # Main categories (shown on overview page)
    "text": "/leaderboard/text/overall",
    "webdev": "/leaderboard/webdev",
    "vision": "/leaderboard/vision",
    "text-to-image": "/leaderboard/text-to-image",
    "image-edit": "/leaderboard/image-edit",
    "search": "/leaderboard/search",
    "text-to-video": "/leaderboard/text-to-video",
    "image-to-video": "/leaderboard/image-to-video",
    # Text subcategories
    "overall": "/leaderboard/text/overall",
    "hard-prompts": "/leaderboard/text/hard-prompts",
    "coding": "/leaderboard/text/coding",
    "math": "/leaderboard/text/math",
    "creative-writing": "/leaderboard/text/creative-writing",
    "instruction-following": "/leaderboard/text/instruction-following",
    "longer-query": "/leaderboard/text/longer-query",
    # Aliases for convenience
    "code": "/leaderboard/text/coding",
    "writing": "/leaderboard/text/creative-writing",
    "video": "/leaderboard/text-to-video",
    "image": "/leaderboard/text-to-image",
}

# Known providers/organizations for validation
KNOWN_PROVIDERS = {
    'anthropic', 'google', 'openai', 'meta', 'mistral', 'deepseek', 'alibaba',
    'cohere', 'nvidia', 'microsoft', 'together', 'perplexity', 'stability',
    'midjourney', 'runway', 'luma', 'pika', 'qwen', 'zhipu', 'baidu',
    '01.ai', 'xai', 'minimax', 'bytedance', 'tencent', 'flux'
}

# Expected top models for validation (at least some should appear)
EXPECTED_MODELS = [
    'gemini', 'claude', 'gpt', 'grok', 'llama', 'deepseek', 'qwen',
    'mistral', 'command', 'o1', 'o3', 'sonnet', 'opus', 'haiku'
]


# ═══════════════════════════════════════════════════════════════════════════════
# Parsing Functions
# ═══════════════════════════════════════════════════════════════════════════════

def parse_lmarena_markdown(markdown: str, category: str) -> List[Dict[str, Any]]:
    """
    Parse LMArena leaderboard data from Firecrawl markdown output.
    
    The actual LMArena table format is:
    | Rank | Rank Spread | Model | Score | 95% CI (±) | Votes | Organization | License |
    | --- | --- | --- | --- | --- | --- | --- | --- |
    | 1 | 1◄─►1 | [gemini-3-pro](url "title") | 1489 | ±5 | 26,385 | Google | Proprietary |
    
    Model names can have prefixes like:
    - Anthropic<br>[claude-opus-4-5]...
    - ![Qwen Icon](img)<br>[qwen3-max]...
    
    Args:
        markdown: Full markdown content from Firecrawl
        category: Category being parsed (for context)
        
    Returns:
        List of ranking dicts with model, score, votes, rank, organization
    """
    rankings = []
    seen_models = set()
    
    # Process each line that looks like a table row
    for line in markdown.split('\n'):
        # Skip non-table lines and header/separator lines
        if not line.startswith('|') or '---' in line:
            continue
        
        # Split by |, filter empty parts
        parts = [p.strip() for p in line.split('|')]
        parts = [p for p in parts if p]  # Remove empty strings
        
        # Skip if not enough columns (Rank, Spread, Model, Score, CI, Votes, Org, License = 8)
        if len(parts) < 6:
            continue
        
        # Try to identify the rank column (first numeric column)
        try:
            # First column should be rank (integer)
            rank_str = parts[0].strip()
            if not rank_str.isdigit():
                continue
            rank = int(rank_str)
        except (ValueError, IndexError):
            continue
        
        # Find model name in the row - it's typically in a [model](url) format
        # The model column is usually at index 2 (after Rank and Rank Spread)
        model_col = None
        model_col_idx = None
        for idx, part in enumerate(parts):
            if '[' in part and '](' in part:
                model_col = part
                model_col_idx = idx
                break
        
        if not model_col:
            continue
        
        # Extract model name from [model-name](url "title") format
        # Handle prefixes like "Anthropic<br>[model]" or "![Icon](img)<br>[model]"
        # We want the LAST markdown link which is usually the actual model name
        all_links = re.findall(r'\[([^\]]+)\]\([^)]+\)', model_col)
        if not all_links:
            continue
        # Take the last link (actual model name) - earlier links are often org names/icons
        model = all_links[-1].strip()
        
        # Find score - it's the next column with a 3-4 digit number after the model
        score = None
        votes = None
        organization = None
        
        # Look for score (3-4 digit number, possibly with "Preliminary")
        for idx in range(model_col_idx + 1, len(parts)):
            part = parts[idx].strip()
            # Skip columns that are likely CI (contain ±)
            if '±' in part:
                continue
            # Match score (might have "Preliminary" suffix)
            score_match = re.match(r'^(\d{3,4})(?:<br>|\s|$)', part)
            if score_match:
                score = int(score_match.group(1))
                break
        
        if score is None or score < 800 or score > 1700:
            continue
        
        # Find votes (number with commas, usually 3-6 digits with comma separators)
        for idx in range(model_col_idx + 1, len(parts)):
            part = parts[idx].strip()
            votes_match = re.match(r'^([\d,]+)$', part)
            if votes_match and ',' in part:  # Has commas = likely votes
                votes = int(votes_match.group(1).replace(',', ''))
                break
        
        # Find organization (column before License, usually after Votes)
        # It's typically a simple string without special characters
        for idx in range(model_col_idx + 3, min(len(parts), model_col_idx + 6)):
            part = parts[idx].strip()
            if part and not re.match(r'^[\d,±]+$', part) and '◄' not in part:
                # Skip columns that are clearly not org names
                if part.lower() not in ('proprietary', 'mit', 'apache 2.0', 'gemma', '---'):
                    if len(part) > 1 and len(part) < 30:
                        organization = part
                        break
        
        # Skip duplicates
        if model.lower() in seen_models:
            continue
        
        seen_models.add(model.lower())
        
        entry = {
            "rank": rank,
            "model": model,
            "score": score,
        }
        
        if votes is not None:
            entry["votes"] = votes
        
        if organization:
            entry["organization"] = organization
        
        rankings.append(entry)
    
    # Sort by rank
    rankings.sort(key=lambda x: x.get("rank", 999))
    
    return rankings


def extract_organization(model_name: str) -> Optional[str]:
    """
    Extract likely organization from model name.
    
    Args:
        model_name: Name of the model
        
    Returns:
        Organization name or None if unknown
    """
    model_lower = model_name.lower()
    
    # Direct mappings
    org_patterns = [
        (r'gemini|palm|bard', 'Google'),
        (r'gpt|chatgpt|o1-|o3-|dall-?e', 'OpenAI'),
        (r'claude|sonnet|opus|haiku', 'Anthropic'),
        (r'grok', 'xAI'),
        (r'llama|meta-', 'Meta'),
        (r'mistral|mixtral|codestral', 'Mistral'),
        (r'deepseek', 'DeepSeek'),
        (r'qwen|qwq', 'Alibaba'),
        (r'command-?r', 'Cohere'),
        (r'yi-|01-?ai', '01.AI'),
        (r'glm|chatglm|zhipu', 'Zhipu'),
        (r'ernie|wenxin', 'Baidu'),
        (r'minimax', 'Minimax'),
        (r'flux', 'Black Forest Labs'),
        (r'imagen|veo', 'Google'),
        (r'sora', 'OpenAI'),
        (r'kling', 'Kuaishou'),
        (r'seedream|seedance', 'ByteDance'),
        (r'hunyuan', 'Tencent'),
        (r'reve', 'Reve'),
        (r'sonar', 'Perplexity'),
    ]
    
    for pattern, org in org_patterns:
        if re.search(pattern, model_lower):
            return org
    
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Validation Functions
# ═══════════════════════════════════════════════════════════════════════════════

def validate_markdown_structure(markdown: str) -> List[str]:
    """
    Validate the raw markdown contains expected table structure.
    
    This helps detect when Firecrawl returns unexpected content (e.g., Cloudflare
    block page, error page, or completely different page structure).
    
    Args:
        markdown: Raw markdown content from Firecrawl
        
    Returns:
        List of warning strings (empty if structure looks valid)
    """
    warnings = []
    
    if not markdown:
        warnings.append("EMPTY_MARKDOWN: Received empty markdown content")
        return warnings
    
    # Check 1: Markdown should have reasonable length
    if len(markdown) < 1000:
        warnings.append(f"SHORT_MARKDOWN: Only {len(markdown)} chars received (expected 10K+)")
    
    # Check 2: Should contain table separators
    if '| --- |' not in markdown and '|---|' not in markdown:
        warnings.append("NO_TABLE_SEPARATOR: Missing markdown table separator (| --- |)")
    
    # Check 3: Should have multiple table rows with rank numbers
    rank_rows = re.findall(r'\|\s*\d+\s*\|', markdown)
    if len(rank_rows) < 10:
        warnings.append(f"FEW_TABLE_ROWS: Only {len(rank_rows)} table rows with ranks found (expected 50+)")
    
    # Check 4: Should contain expected column headers
    expected_headers = ['Rank', 'Model', 'Score', 'Votes']
    header_found = sum(1 for h in expected_headers if h.lower() in markdown.lower())
    if header_found < 3:
        warnings.append(f"MISSING_HEADERS: Only {header_found}/4 expected column headers found")
    
    # Check 5: Check for Cloudflare/captcha indicators
    # These patterns indicate actual block pages, not just words that might appear naturally
    markdown_lower = markdown.lower()
    
    # Strong indicators (multiple words together that indicate a block page)
    cloudflare_block_patterns = [
        ('checking your browser', 'please wait'),  # Cloudflare challenge page
        ('just a moment', 'enable javascript'),     # JS challenge
        ('ddos protection', 'cloudflare'),          # DDoS page
        ('ray id', 'cloudflare'),                   # Cloudflare error page
        ('access denied', 'cloudflare'),            # Blocked by Cloudflare
        ('verify you are human', 'captcha'),        # Captcha challenge
    ]
    
    for pattern_pair in cloudflare_block_patterns:
        if all(p in markdown_lower for p in pattern_pair):
            warnings.append(f"CLOUDFLARE_DETECTED: Found '{pattern_pair[0]}' + '{pattern_pair[1]}' - likely blocked by Cloudflare")
            break
    
    # Also check if page is suspiciously short with no table content
    if len(markdown) < 5000 and '| --- |' not in markdown:
        # Short page without tables - might be a block page
        block_keywords = ['blocked', 'denied', 'forbidden', 'unauthorized']
        found_block = [k for k in block_keywords if k in markdown_lower]
        if found_block:
            warnings.append(f"POSSIBLE_BLOCK: Short page ({len(markdown)} chars) with '{found_block[0]}' - might be blocked")
    
    # Check 6: Should contain model links (LMArena format)
    model_links = re.findall(r'\[[^\]]+\]\([^)]+\)', markdown)
    if len(model_links) < 10:
        warnings.append(f"FEW_MODEL_LINKS: Only {len(model_links)} markdown links found (expected many)")
    
    return warnings


def validate_rankings(rankings: List[Dict], category: str, markdown: str = "") -> Dict[str, Any]:
    """
    Comprehensive validation of scraped rankings data to detect scraper breakage.
    
    This function performs multiple checks to ensure:
    1. Data was successfully extracted (not empty)
    2. Data structure is correct (required fields present)
    3. Data values are reasonable (scores, votes in expected ranges)
    4. Expected content is present (known models, multiple orgs)
    5. Raw markdown structure was valid (no Cloudflare block, proper tables)
    
    Args:
        rankings: List of ranking dicts
        category: Category being validated
        markdown: Raw markdown content (optional, for structure validation)
    
    Returns:
        Dict with:
        - valid (bool): True if all critical checks pass
        - warnings (list): List of warning strings
        - metrics (dict): Data quality metrics
    """
    warnings = []
    metrics = {}
    
    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1: Raw markdown structure validation
    # ─────────────────────────────────────────────────────────────────────────
    if markdown:
        structure_warnings = validate_markdown_structure(markdown)
        warnings.extend(structure_warnings)
        metrics["markdown_length"] = len(markdown)
    
    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2: Data presence checks
    # ─────────────────────────────────────────────────────────────────────────
    
    # Check 1: Did we get any data?
    if not rankings:
        warnings.append("NO_DATA: No rankings extracted - parser may be broken or page structure changed")
        return {
            "valid": False,
            "warnings": warnings,
            "metrics": metrics
        }
    
    metrics["model_count"] = len(rankings)
    
    # Check 2: Got enough models?
    if len(rankings) < 10:
        warnings.append(f"LOW_COUNT: Only {len(rankings)} models found (expected 50+)")
    elif len(rankings) < 30:
        warnings.append(f"MODERATE_COUNT: Only {len(rankings)} models found (expected 50+, might be truncated)")
    
    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3: Data structure validation
    # ─────────────────────────────────────────────────────────────────────────
    
    # Check required fields
    required_fields = ["rank", "model", "score"]
    optional_fields = ["votes", "organization"]
    
    models_with_all_required = 0
    models_with_votes = 0
    models_with_org = 0
    malformed_entries = []
    
    for i, r in enumerate(rankings):
        has_required = all(r.get(f) is not None for f in required_fields)
        if has_required:
            models_with_all_required += 1
        else:
            missing = [f for f in required_fields if r.get(f) is None]
            malformed_entries.append(f"Entry {i}: missing {missing}")
        
        if r.get("votes") is not None:
            models_with_votes += 1
        if r.get("organization"):
            models_with_org += 1
    
    metrics["models_with_required_fields"] = models_with_all_required
    metrics["models_with_votes"] = models_with_votes
    metrics["models_with_org"] = models_with_org
    metrics["completeness_pct"] = round(models_with_all_required / len(rankings) * 100, 1) if rankings else 0
    metrics["votes_pct"] = round(models_with_votes / len(rankings) * 100, 1) if rankings else 0
    metrics["org_pct"] = round(models_with_org / len(rankings) * 100, 1) if rankings else 0
    
    if models_with_all_required < len(rankings) * 0.9:
        warnings.append(f"INCOMPLETE_DATA: Only {models_with_all_required}/{len(rankings)} entries have all required fields")
    
    if models_with_votes < len(rankings) * 0.8:
        warnings.append(f"MISSING_VOTES: Only {models_with_votes}/{len(rankings)} entries have vote counts")
    
    if malformed_entries and len(malformed_entries) <= 5:
        warnings.append(f"MALFORMED_ENTRIES: {', '.join(malformed_entries[:5])}")
    
    # ─────────────────────────────────────────────────────────────────────────
    # Phase 4: Data value validation
    # ─────────────────────────────────────────────────────────────────────────
    
    # Check scores
    scores = [r.get("score", 0) for r in rankings if r.get("score")]
    if scores:
        min_score = min(scores)
        max_score = max(scores)
        avg_score = sum(scores) / len(scores)
        
        metrics["score_min"] = min_score
        metrics["score_max"] = max_score
        metrics["score_avg"] = round(avg_score, 1)
        
        # Elo scores should be in 800-1700 range typically
        if max_score < 1200:
            warnings.append(f"LOW_MAX_SCORE: Max score is only {max_score} (expected ~1400-1500 for top models)")
        if max_score > 1800:
            warnings.append(f"HIGH_MAX_SCORE: Max score is {max_score} (unusually high, possible parsing error)")
        if min_score < 800:
            warnings.append(f"LOW_MIN_SCORE: Min score is {min_score} (below typical Elo range)")
        if max_score - min_score < 50:
            warnings.append(f"NARROW_SCORE_RANGE: Score range is only {max_score - min_score} (expected 200+ spread)")
    
    # Check votes
    votes = [r.get("votes") for r in rankings if r.get("votes") is not None]
    if votes:
        min_votes = min(votes)
        max_votes = max(votes)
        total_votes = sum(votes)
        
        metrics["votes_min"] = min_votes
        metrics["votes_max"] = max_votes
        metrics["votes_total"] = total_votes
        
        # Top models should have tens of thousands of votes
        if max_votes < 1000:
            warnings.append(f"LOW_VOTES: Max votes is only {max_votes} (expected 10K+ for top models)")
        if total_votes < 10000:
            warnings.append(f"LOW_TOTAL_VOTES: Total votes is only {total_votes} (expected millions)")
    
    # Check ranks
    ranks = [r.get("rank", 0) for r in rankings if r.get("rank")]
    if ranks:
        metrics["rank_min"] = min(ranks)
        metrics["rank_max"] = max(ranks)
        
        # Check for rank continuity (no big gaps)
        sorted_ranks = sorted(ranks)
        gaps = []
        for i in range(1, len(sorted_ranks)):
            gap = sorted_ranks[i] - sorted_ranks[i-1]
            if gap > 5:
                gaps.append(f"{sorted_ranks[i-1]}->{sorted_ranks[i]}")
        
        if gaps and len(gaps) <= 3:
            warnings.append(f"RANK_GAPS: Large gaps in rankings: {', '.join(gaps[:3])}")
        elif len(gaps) > 3:
            warnings.append(f"MANY_RANK_GAPS: {len(gaps)} large gaps in rankings (possible parsing issues)")
    
    # ─────────────────────────────────────────────────────────────────────────
    # Phase 5: Content validation
    # ─────────────────────────────────────────────────────────────────────────
    
    # Check for expected models
    model_names_lower = [r.get("model", "").lower() for r in rankings]
    found_expected = []
    
    for expected in EXPECTED_MODELS:
        if any(expected in name for name in model_names_lower):
            found_expected.append(expected)
    
    metrics["expected_models_found"] = len(found_expected)
    metrics["expected_models_list"] = found_expected[:5]  # First 5 for brevity
    
    if len(found_expected) == 0:
        warnings.append("NO_EXPECTED_MODELS: None of the expected models found (Claude, GPT, Gemini, etc.) - parser likely broken")
    elif len(found_expected) < 3:
        warnings.append(f"FEW_EXPECTED_MODELS: Only {len(found_expected)} expected model families found: {found_expected}")
    
    # Check organization diversity
    orgs = set(r.get("organization", "").lower() for r in rankings if r.get("organization"))
    metrics["unique_orgs"] = len(orgs)
    
    if len(orgs) < 3:
        warnings.append(f"LOW_ORG_DIVERSITY: Only {len(orgs)} unique organizations found (expected 5+)")
    
    # Verify top models have expected properties
    top_5 = rankings[:5] if len(rankings) >= 5 else rankings
    top_5_valid = all(
        r.get("rank") and r.get("model") and r.get("score") and r.get("score") > 1300
        for r in top_5
    )
    if not top_5_valid:
        warnings.append("TOP_5_INVALID: Top 5 models don't have expected structure/scores (top models should have score > 1300)")
    
    # ─────────────────────────────────────────────────────────────────────────
    # Phase 6: Category-specific validation
    # ─────────────────────────────────────────────────────────────────────────
    
    # For text category, we expect certain flagship models near the top
    if category in ("text", "overall"):
        flagship_models = ["gemini", "claude", "gpt", "grok"]
        top_20_models = [r.get("model", "").lower() for r in rankings[:20]]
        flagships_found = sum(1 for fm in flagship_models if any(fm in m for m in top_20_models))
        
        if flagships_found < 2:
            warnings.append(f"MISSING_FLAGSHIPS: Only {flagships_found}/4 flagship model families in top 20")
    
    # ─────────────────────────────────────────────────────────────────────────
    # Determine overall validity
    # ─────────────────────────────────────────────────────────────────────────
    
    # Critical warnings that indicate definite scraper breakage
    critical_prefixes = [
        "NO_DATA", "NO_EXPECTED_MODELS", "CLOUDFLARE_DETECTED",
        "EMPTY_MARKDOWN", "NO_TABLE_SEPARATOR"
    ]
    
    has_critical = any(
        any(w.startswith(prefix) for prefix in critical_prefixes)
        for w in warnings
    )
    
    return {
        "valid": not has_critical and len(warnings) <= 2,  # Allow up to 2 non-critical warnings
        "warnings": warnings,
        "metrics": metrics
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Main Fetching Logic
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_lmarena_rankings(category: str = "text", limit: int = 50) -> Dict[str, Any]:
    """
    Fetch LMArena rankings for a category using Firecrawl.
    
    Args:
        category: Category name (text, webdev, coding, etc.)
        limit: Max number of models to return
    
    Returns:
        Dict with rankings data and metadata
    """
    # Normalize category
    category_lower = category.lower().strip()
    if category_lower not in CATEGORIES:
        available = ", ".join(sorted(CATEGORIES.keys()))
        script_logger.warning(f"Unknown category '{category}'. Available: {available}")
        category_lower = "text"
    
    url_path = CATEGORIES[category_lower]
    url = f"{BASE_URL}{url_path}"
    
    script_logger.info(f"Fetching LMArena leaderboard ({category_lower})...")
    script_logger.info(f"URL: {url}")
    
    try:
        # Initialize SecretsManager for Vault access
        secrets_manager = SecretsManager()
        await secrets_manager.initialize()
        
        # Scrape with Firecrawl (handles JS rendering)
        result = await scrape_url(
            url=url,
            secrets_manager=secrets_manager,
            formats=["markdown"],
            only_main_content=True,
            sanitize_output=False  # Don't sanitize ranking data
        )
        
        # Clean up SecretsManager
        await secrets_manager.aclose()
        
        if result.get("error"):
            script_logger.error(f"Firecrawl error: {result['error']}")
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": url,
                "category": category_lower,
                "rankings": [],
                "model_count": 0,
                "validation": {"valid": False, "warnings": [f"FIRECRAWL_ERROR: {result['error']}"]}
            }
        
        # Extract markdown content
        markdown_content = result.get("data", {}).get("markdown", "")
        
        if not markdown_content:
            script_logger.error("Firecrawl returned empty markdown")
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": url,
                "category": category_lower,
                "rankings": [],
                "model_count": 0,
                "validation": {"valid": False, "warnings": ["EMPTY_RESPONSE: Firecrawl returned empty content"]}
            }
        
        script_logger.info(f"Received {len(markdown_content)} chars of markdown")
        
        # Parse rankings from markdown
        rankings = parse_lmarena_markdown(markdown_content, category_lower)
        
        # Add organization info
        for r in rankings:
            org = extract_organization(r.get("model", ""))
            if org:
                r["organization"] = org
        
        # Limit results
        rankings = rankings[:limit]
        
        # Validate with raw markdown for structure checks
        validation = validate_rankings(rankings, category_lower, markdown=markdown_content)
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": url,
            "category": category_lower,
            "rankings": rankings,
            "model_count": len(rankings),
            "validation": validation,
        }
        
    except Exception as e:
        script_logger.error(f"Error fetching rankings: {e}", exc_info=True)
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": url,
            "category": category_lower,
            "rankings": [],
            "model_count": 0,
            "validation": {"valid": False, "warnings": [f"EXCEPTION: {str(e)}"]}
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Output Functions
# ═══════════════════════════════════════════════════════════════════════════════

def print_rankings(data: Dict[str, Any], as_json: bool = False) -> None:
    """
    Print rankings in human-readable or JSON format.
    
    Args:
        data: Rankings data dict
        as_json: Output as JSON if True
    """
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    
    validation = data.get("validation", {})
    is_valid = validation.get("valid", True)
    warnings = validation.get("warnings", [])
    metrics = validation.get("metrics", {})
    
    print(f"\n{'═' * 75}")
    print(f"📊 LMARENA LEADERBOARD")
    print(f"{'═' * 75}")
    print(f"Source:   {data.get('source')}")
    print(f"Category: {data.get('category')}")
    print(f"Models:   {data.get('model_count', 0)}")
    print(f"Status:   {'✅ Valid' if is_valid else '⚠️  WARNINGS DETECTED'}")
    print(f"Time:     {data.get('timestamp')}")
    
    # Print data quality metrics if available
    if metrics:
        print(f"\n📈 Data Quality Metrics:")
        if "completeness_pct" in metrics:
            print(f"   Completeness: {metrics['completeness_pct']}% have all required fields")
        if "votes_pct" in metrics:
            print(f"   Votes:        {metrics['votes_pct']}% have vote counts")
        if "org_pct" in metrics:
            print(f"   Orgs:         {metrics['org_pct']}% have organization")
        if "expected_models_found" in metrics:
            found = metrics.get("expected_models_list", [])
            print(f"   Top Brands:   {metrics['expected_models_found']} found ({', '.join(found[:4])})")
        if "score_max" in metrics:
            print(f"   Score Range:  {metrics.get('score_min', 'N/A')}-{metrics['score_max']}")
        if "unique_orgs" in metrics:
            print(f"   Unique Orgs:  {metrics['unique_orgs']}")
    
    # Print warnings if any
    if warnings:
        # Separate critical vs non-critical
        critical_prefixes = ["NO_DATA", "NO_EXPECTED_MODELS", "CLOUDFLARE_DETECTED", 
                          "EMPTY_MARKDOWN", "NO_TABLE_SEPARATOR"]
        critical = [w for w in warnings if any(w.startswith(p) for p in critical_prefixes)]
        other = [w for w in warnings if w not in critical]
        
        if critical:
            print(f"\n🚨 CRITICAL WARNINGS ({len(critical)}) - Scraper likely broken:")
            for w in critical:
                print(f"   ❌ {w}")
        
        if other:
            print(f"\n⚠️  Warnings ({len(other)}):")
            for w in other:
                print(f"   - {w}")
    
    rankings = data.get("rankings", [])
    
    if not rankings:
        print("\n⚠️  No rankings found.")
        print("   This might be due to:")
        print("   - Cloudflare blocking the request")
        print("   - Page structure changed")
        print("   - API key issues")
        return
    
    print(f"\n{'─' * 75}")
    print(f"{'#':<4} {'Model':<40} {'Score':<8} {'Votes':<12} {'Org':<15}")
    print(f"{'─' * 75}")
    
    for r in rankings:
        rank = r.get("rank", "-")
        model = r.get("model", "")[:38]
        if len(r.get("model", "")) > 38:
            model += ".."
        score = r.get("score", "-")
        votes = r.get("votes")
        votes_str = f"{votes:,}" if votes else "-"
        org = r.get("organization", "-")[:13]
        
        print(f"{rank:<4} {model:<40} {score:<8} {votes_str:<12} {org:<15}")


def list_categories() -> None:
    """Print available categories."""
    print("\n📊 Available LMArena Categories:")
    print("=" * 50)
    
    main_cats = ["text", "webdev", "vision", "text-to-image", "image-edit", "search", "text-to-video", "image-to-video"]
    text_cats = ["overall", "hard-prompts", "coding", "math", "creative-writing", "instruction-following", "longer-query"]
    
    print("\nMain Categories:")
    for cat in main_cats:
        print(f"  - {cat}")
    
    print("\nText Subcategories:")
    for cat in text_cats:
        print(f"  - {cat}")
    
    print("\nAliases:")
    print("  - code (→ coding)")
    print("  - writing (→ creative-writing)")
    print("  - video (→ text-to-video)")
    print("  - image (→ text-to-image)")


# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Fetch LMArena (Chatbot Arena) leaderboard rankings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run inside Docker (uses Vault API key)
  docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py
  docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py --category coding
  docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py -o /app/lmarena.json

Categories: text, webdev, vision, coding, math, creative-writing, search, etc.
Use --list-categories to see all available categories.
        """
    )
    parser.add_argument("--category", "-c", default="text", help="Category (text, webdev, coding, etc.)")
    parser.add_argument("--limit", "-n", type=int, default=50, help="Max models to return (default: 50)")
    parser.add_argument("--json", "-j", action="store_true", help="JSON output")
    parser.add_argument("--output", "-o", help="Save to file")
    parser.add_argument("--list-categories", "-l", action="store_true", help="List available categories")
    
    args = parser.parse_args()
    
    if args.list_categories:
        list_categories()
        return
    
    # Run async fetch
    data = asyncio.run(fetch_lmarena_rankings(args.category, args.limit))
    
    # Print warnings to stderr
    validation = data.get("validation", {})
    if validation.get("warnings"):
        for w in validation["warnings"]:
            script_logger.warning(w)
    
    if args.output:
        with open(args.output, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✓ Saved to {args.output}")
    else:
        print_rankings(data, as_json=args.json)


if __name__ == "__main__":
    main()
