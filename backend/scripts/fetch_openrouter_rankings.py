#!/usr/bin/env python3
"""
Fetches AI model rankings from OpenRouter.ai using Firecrawl for JavaScript rendering.

This script:
1. Uses Firecrawl API (via Vault) to scrape the dynamically-rendered rankings page
2. Supports category-specific leaderboards (programming, roleplay, marketing, legal, etc.)
3. Validates the output to detect when the scraper breaks

Usage:
    # General leaderboard
    docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py
    
    # Category-specific leaderboard
    docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py --category programming
    docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py --category roleplay
    
    # All categories
    docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py --all-categories

Options:
    --category CAT    Fetch leaderboard for specific category
    --all-categories  Fetch leaderboards for all known categories
    --json            Output as JSON instead of formatted text
    -o, --output FILE Save output to file
    --basic           Use basic HTML parsing (no Firecrawl API)
"""

import asyncio
import argparse
import json
import logging
import re
import sys
import urllib.request
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

script_logger = logging.getLogger('fetch_openrouter_rankings')
script_logger.setLevel(logging.INFO)

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

BASE_URL = "https://openrouter.ai/rankings"

# Available categories (based on OpenRouter's categories dropdown)
# URL format: https://openrouter.ai/rankings/{category}
#
# NOTE: Due to OpenRouter's SPA architecture, navigating to /rankings/{category}
# does NOT automatically select that category in the UI dropdown. The "Categories"
# section always defaults to showing "Programming" data regardless of the URL path.
# This is a limitation of the website's client-side navigation.
#
# The script will still capture whatever category data is shown on the page,
# which is currently always "Programming" for the Categories section.
AVAILABLE_CATEGORIES = [
    "programming",  # The only category reliably captured due to being the default
    # The following are available in the UI but not auto-selected via URL:
    # "roleplay", "marketing", "legal", "customer-support", "data-analysis",
    # "creative-writing", "research", "education", "general"
]

# Known providers for validation
KNOWN_PROVIDERS = {"anthropic", "google", "openai", "meta", "mistralai", "deepseek", "x-ai", "cohere", "xiaomi", "z-ai"}

# Expected models in leaderboard (should find at least one)
EXPECTED_MODEL_KEYWORDS = {"claude", "gpt", "gemini", "llama", "mistral", "deepseek", "grok"}

# Firecrawl wait time (ms) to allow JavaScript to render category-specific data
FIRECRAWL_WAIT_TIME = 5000


# ═══════════════════════════════════════════════════════════════════════════════
# Parsing Functions
# ═══════════════════════════════════════════════════════════════════════════════

def parse_leaderboard(markdown_content: str) -> List[Dict[str, Any]]:
    """
    Parse the LLM Leaderboard section from Firecrawl markdown.
    
    Format (multi-line entries, may include favicon images):
    ```
    1.
    ![Favicon for google](https://openrouter.ai/images/icons/GoogleGemini.svg)
    [Gemini 3 Flash Preview](https://openrouter.ai/google/gemini-3-flash-preview)
    by [google](https://openrouter.ai/google)
    764B tokens
    40%
    ```
    
    Args:
        markdown_content: Full markdown from Firecrawl
        
    Returns:
        List of parsed leaderboard entries
    """
    rankings = []
    
    # Find the leaderboard section - handle both "LLM Leaderboard" and "## LLM Leaderboard"
    leaderboard_start = markdown_content.find("LLM Leaderboard")
    # Find "Market Share" or "[**Market Share**]" as end marker
    market_share_start = markdown_content.find("Market Share")
    
    if leaderboard_start == -1:
        return rankings
    
    # Extract leaderboard section
    if market_share_start != -1:
        section = markdown_content[leaderboard_start:market_share_start]
    else:
        section = markdown_content[leaderboard_start:leaderboard_start + 8000]
    
    # Split into lines and group by rank markers
    lines = section.split('\n')
    entries = []
    current_entry_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # New rank marker (just "1." or "2." etc.)
        if re.match(r'^\d+\.$', line):
            if current_entry_lines:
                entries.append(' '.join(current_entry_lines))
            current_entry_lines = [line]
        # Stop at "Show more" or section end markers
        elif line == "Show more" or line.startswith("[**"):
            break
        else:
            current_entry_lines.append(line)
    
    if current_entry_lines:
        entries.append(' '.join(current_entry_lines))
    
    # Parse each joined entry
    for entry_text in entries:
        # Strip inline favicon images: ![Favicon for ...](url)
        # These appear before the model link in the current format
        cleaned = re.sub(r'!\[[^\]]*\]\([^)]+\)\s*', '', entry_text)
        
        # Pattern: "1. [Model](url) by [provider](url) 764B tokens 40%"
        # Also handles: "1. [Model](url) by [provider](url) 764B 40%"
        match = re.match(
            r'(\d+)\.\s*'
            r'\[([^\]]+)\]\((https?://openrouter\.ai/[^)]+)\)\s*'
            r'(?:by\s*\[([^\]]+)\]\((https?://openrouter\.ai/[^)]+)\)\s*)?'
            r'([\d,\.]+[BKMGT]?)\s*(?:tokens?)?\s*'
            r'([\d,\.]+%)?',
            cleaned
        )
        if match:
            rank, model_name, model_url, provider_name, provider_url, tokens, share = match.groups()
            # Extract slug from URL
            slug_parts = model_url.rstrip('/').split('/')
            slug = '/'.join(slug_parts[-2:]) if len(slug_parts) >= 2 else slug_parts[-1]
            
            rankings.append({
                "rank": int(rank),
                "model": model_name.strip(),
                "provider": provider_name.strip() if provider_name else slug_parts[-2] if len(slug_parts) >= 2 else None,
                "slug": slug,
                "tokens": tokens.strip(),
                "share": share.strip() if share else None,
                "url": model_url,
            })
    
    return rankings


def parse_top_apps(markdown_content: str) -> List[Dict[str, Any]]:
    """
    Parse the Top Apps section from Firecrawl markdown.
    
    Args:
        markdown_content: Full markdown from Firecrawl
        
    Returns:
        List of parsed top apps
    """
    apps = []
    
    # Find Top Apps section
    apps_start = markdown_content.find("Top Apps")
    if apps_start == -1:
        return apps
    
    section = markdown_content[apps_start:apps_start + 3000]
    
    # Pattern for apps: "[App Name](url) description tokens"
    # Example: [Kilo Code](https://openrouter.ai/apps?url=...) AI coding agent for VS Code 59.3Btokens
    
    lines = section.split('\n')
    entries = []
    current_entry_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if re.match(r'^\d+\.$', line):
            if current_entry_lines:
                entries.append(' '.join(current_entry_lines))
            current_entry_lines = [line]
        else:
            current_entry_lines.append(line)
    
    if current_entry_lines:
        entries.append(' '.join(current_entry_lines))
    
    for entry_text in entries:
        # Pattern for apps
        match = re.search(
            r'(\d+)\.\s*'
            r'(?:!\[[^\]]*\]\([^)]+\)\s*)?'  # Optional favicon image
            r'\[([^\]]+)\]\((https?://[^)]+)\)\s*'  # App name and URL
            r'([^0-9]*?)'  # Description
            r'([\d\.]+[BKMGT]?)(?:tokens)?',  # Tokens
            entry_text
        )
        if match:
            rank, app_name, app_url, description, tokens = match.groups()
            apps.append({
                "rank": int(rank),
                "app": app_name.strip(),
                "url": app_url,
                "description": description.strip() if description else None,
                "tokens": tokens.strip(),
            })
    
    return apps


def parse_category_leaderboard(markdown_content: str, category: str) -> List[Dict[str, Any]]:
    """
    Parse the category-specific leaderboard from the "Categories" section.
    
    When navigating to /rankings/{category}, the "Categories" section shows 
    the leaderboard filtered for that specific category (e.g., programming, roleplay).
    
    Format (after JavaScript renders with 5s wait):
    ```
    [**Categories**](https://openrouter.ai/rankings/programming#categories)
    Compare models by usecase on OpenRouter
    Programming
    Oct 6, 2025Oct 13...  (chart labels)
    1.
    [Grok Code Fast 1](https://openrouter.ai/x-ai/grok-code-fast-1)
    by [x-ai](https://openrouter.ai/x-ai)
    200B
    25.1%
    ```
    
    Args:
        markdown_content: Full markdown from Firecrawl (with waitFor=5000)
        category: The category being fetched (e.g., "programming")
        
    Returns:
        List of parsed category leaderboard entries
    """
    rankings = []
    
    # Find the Categories section
    categories_start = markdown_content.find("[**Categories**]")
    if categories_start == -1:
        # Try alternative markers
        categories_start = markdown_content.find("**Categories**")
    
    if categories_start == -1:
        return rankings
    
    # Find the end of the Categories section (next major section)
    section_end_markers = ["[**Languages**]", "[**Programming**]", "[**Context Length**]", "[**Tool Calls**]"]
    section_end = len(markdown_content)
    for marker in section_end_markers:
        pos = markdown_content.find(marker, categories_start + 50)
        if pos != -1 and pos < section_end:
            section_end = pos
    
    section = markdown_content[categories_start:section_end]
    
    # Split into lines and group by rank markers
    lines = section.split('\n')
    entries = []
    current_entry_lines = []
    
    # Skip the header lines (title, description, category name, chart labels)
    in_entries = False
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Detect start of numbered entries
        if re.match(r'^\d+\.$', line):
            in_entries = True
            if current_entry_lines:
                entries.append(' '.join(current_entry_lines))
            current_entry_lines = [line]
        elif in_entries:
            # Stop at "Others" or section end
            if line.startswith('[Others]') or '[**' in line:
                break
            current_entry_lines.append(line)
    
    if current_entry_lines:
        entries.append(' '.join(current_entry_lines))
    
    # Parse each joined entry (same pattern as general leaderboard)
    for entry_text in entries:
        # Strip inline favicon images: ![Favicon for ...](url)
        cleaned = re.sub(r'!\[[^\]]*\]\([^)]+\)\s*', '', entry_text)
        
        # Pattern: "1. [Model](url) by [provider](url) 200B 25.1%"
        match = re.match(
            r'(\d+)\.\s*'
            r'\[([^\]]+)\]\((https?://openrouter\.ai/[^)]+)\)\s*'
            r'(?:by\s*\[([^\]]+)\]\((https?://openrouter\.ai/[^)]+)\)\s*)?'
            r'([\d,\.]+[BKMGT]?)\s*'
            r'([\d,\.]+%)?',
            cleaned
        )
        if match:
            rank, model_name, model_url, provider_name, provider_url, tokens, share = match.groups()
            # Extract slug from URL
            slug_parts = model_url.rstrip('/').split('/')
            slug = '/'.join(slug_parts[-2:]) if len(slug_parts) >= 2 else slug_parts[-1]
            
            rankings.append({
                "rank": int(rank),
                "model": model_name.strip(),
                "provider": provider_name.strip() if provider_name else slug_parts[-2] if len(slug_parts) >= 2 else None,
                "slug": slug,
                "tokens": tokens.strip(),
                "share": share.strip() if share else None,
                "url": model_url,
            })
    
    return rankings


def parse_basic_html(html_content: str) -> List[Dict[str, Any]]:
    """
    Parse basic HTML for the leaderboard (fallback mode without Firecrawl).
    
    Args:
        html_content: Raw HTML from the page
        
    Returns:
        List of parsed leaderboard entries
    """
    rankings = []
    
    # Pattern for leaderboard entries in HTML
    pattern = re.compile(
        r'href="/([\w-]+)/([\w\-:\.]+)"[^>]*>([^<]+)</a>'
        r'.*?by.*?href="/([\w-]+)"[^>]*>[\w-]+</a>'
        r'.*?([\d\.]+[BKMGT])\s*tokens?',
        re.DOTALL
    )
    
    for i, match in enumerate(pattern.finditer(html_content), 1):
        provider, slug, model_name, provider2, tokens = match.groups()
        rankings.append({
            "rank": i,
            "model": model_name.strip(),
            "provider": provider.strip(),
            "slug": f"{provider}/{slug}",
            "tokens": tokens.strip(),
            "share": None,
            "url": f"https://openrouter.ai/{provider}/{slug}",
        })
        if i >= 10:
            break
    
    return rankings


# ═══════════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════════

def validate_results(
    leaderboard: List[Dict], 
    top_apps: List[Dict], 
    category_leaderboard: Optional[List[Dict]] = None,
    category: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate scraped results to detect when the scraper breaks.
    
    Args:
        leaderboard: Parsed general leaderboard entries
        top_apps: Parsed top apps entries
        category_leaderboard: Parsed category-specific leaderboard entries (optional)
        category: Category name if fetching category-specific data
        
    Returns:
        Dict with 'valid' bool and 'warnings' list
    """
    warnings = []
    
    # If fetching a specific category, validate the category leaderboard
    if category and category_leaderboard is not None:
        if not category_leaderboard:
            warnings.append(f"NO_CATEGORY_DATA: '{category}' leaderboard empty - scraper may be broken")
        elif len(category_leaderboard) < 3:
            warnings.append(f"LOW_COUNT: Only {len(category_leaderboard)} entries for '{category}' (expected 5+)")
        
        # Validate category data has known providers/models
        if category_leaderboard:
            providers_found = {e.get("provider", "").lower() for e in category_leaderboard if e.get("provider")}
            known_found = providers_found & KNOWN_PROVIDERS
            if not known_found:
                warnings.append("UNKNOWN_PROVIDERS: No known providers in category data")
        
        return {
            "valid": len(warnings) == 0,
            "warnings": warnings
        }
    
    # General validation (no category specified)
    # Check 1: Any leaderboard data?
    if not leaderboard:
        warnings.append("NO_LEADERBOARD: Leaderboard empty - scraper may be broken")
    elif len(leaderboard) < 5:
        warnings.append(f"LOW_COUNT: Only {len(leaderboard)} leaderboard entries (expected 10)")
    
    # Check 2: Known providers present
    if leaderboard:
        providers_found = {e.get("provider", "").lower() for e in leaderboard if e.get("provider")}
        known_found = providers_found & KNOWN_PROVIDERS
        if not known_found:
            warnings.append("UNKNOWN_PROVIDERS: No known providers found")
    
    # Check 3: Expected models present
    if leaderboard:
        models_found = {e.get("model", "").lower() for e in leaderboard}
        found_expected = any(
            any(kw in model for kw in EXPECTED_MODEL_KEYWORDS)
            for model in models_found
        )
        if not found_expected:
            warnings.append("UNEXPECTED_MODELS: No expected models (Claude, GPT, Gemini, etc.)")
    
    # Check 4: Top apps (optional but useful)
    if not top_apps:
        warnings.append("NO_TOP_APPS: Top Apps section empty (may be okay)")
    
    return {
        "valid": len([w for w in warnings if not w.startswith("NO_TOP_APPS")]) == 0,
        "warnings": warnings
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Main Functions
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_rankings(basic_mode: bool = False, category: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch rankings from OpenRouter.
    
    Args:
        basic_mode: If True, use basic HTML parsing (no Firecrawl)
        category: Optional category to fetch (e.g., "programming", "roleplay")
                  When specified, returns the category-specific leaderboard
        
    Returns:
        Dict with timestamp, leaderboard/category_leaderboard, top_apps, and validation
    """
    # Build URL with category if specified
    if category:
        url = f"{BASE_URL}/{category.lower()}"
    else:
        url = BASE_URL
    
    if basic_mode:
        script_logger.info(f"Fetching {url} (basic HTML mode)...")
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                html = response.read().decode('utf-8')
        except Exception as e:
            script_logger.error(f"Failed to fetch URL: {e}")
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": url,
                "method": "basic",
                "category": category,
                "leaderboard": [],
                "top_apps": [],
                "validation": {"valid": False, "warnings": [f"FETCH_ERROR: {e}"]}
            }
        
        leaderboard = parse_basic_html(html)
        top_apps = []
        category_leaderboard = []
        
    else:
        script_logger.info(f"Fetching {url} via Firecrawl{' (category: ' + category + ')' if category else ''}...")
        
        # Initialize SecretsManager for Vault access
        secrets_manager = SecretsManager()
        await secrets_manager.initialize()
        
        try:
            # When fetching category-specific data, we need a longer wait time
            # for JavaScript to render the filtered leaderboard
            wait_time = FIRECRAWL_WAIT_TIME if category else 0
            
            result = await scrape_url(
                url=url,
                secrets_manager=secrets_manager,
                formats=["markdown"],
                only_main_content=True,
                max_age=3600000,  # 1 hour cache
                sanitize_output=False,
                wait_for=wait_time  # Wait for JS to render category data
            )
            
            if result.get("error"):
                script_logger.error(f"Firecrawl error: {result['error']}")
                return {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": url,
                    "method": "firecrawl",
                    "category": category,
                    "leaderboard": [],
                    "top_apps": [],
                    "validation": {"valid": False, "warnings": [f"FIRECRAWL_ERROR: {result['error']}"]}
                }
            
            markdown = result.get("data", {}).get("markdown", "")
            if not markdown:
                return {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": url,
                    "method": "firecrawl",
                    "category": category,
                    "leaderboard": [],
                    "top_apps": [],
                    "validation": {"valid": False, "warnings": ["EMPTY_RESPONSE: Firecrawl returned empty content"]}
                }
            
            # Parse general leaderboard and top apps (always available)
            leaderboard = parse_leaderboard(markdown)
            top_apps = parse_top_apps(markdown)
            
            # Parse category-specific leaderboard if category specified
            if category:
                category_leaderboard = parse_category_leaderboard(markdown, category)
            else:
                category_leaderboard = []
            
        except Exception as e:
            script_logger.error(f"Firecrawl failed: {e}")
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": url,
                "method": "firecrawl",
                "category": category,
                "leaderboard": [],
                "top_apps": [],
                "validation": {"valid": False, "warnings": [f"EXCEPTION: {e}"]}
            }
    
    # Validate based on what we're fetching
    if category:
        validation = validate_results(leaderboard, top_apps, category_leaderboard, category)
    else:
        validation = validate_results(leaderboard, top_apps)
    
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": url,
        "method": "basic" if basic_mode else "firecrawl",
        "leaderboard": leaderboard,
        "top_apps": top_apps,
        "validation": validation
    }
    
    # Add category-specific data if fetching a category
    if category:
        result["category"] = category
        result["category_leaderboard"] = category_leaderboard
    
    return result


async def fetch_all_categories(basic_mode: bool = False) -> Dict[str, Any]:
    """
    Fetch rankings for all available categories.
    
    Args:
        basic_mode: If True, use basic HTML parsing (no Firecrawl)
        
    Returns:
        Dict with all category leaderboards
    """
    script_logger.info(f"Fetching rankings for {len(AVAILABLE_CATEGORIES)} categories...")
    
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "categories": {}
    }
    
    all_valid = True
    all_warnings = []
    
    for category in AVAILABLE_CATEGORIES:
        script_logger.info(f"  Fetching {category}...")
        data = await fetch_rankings(basic_mode=basic_mode, category=category)
        
        results["categories"][category] = {
            "leaderboard": data.get("category_leaderboard", []),
            "source": data.get("source"),
            "validation": data.get("validation", {})
        }
        
        if not data.get("validation", {}).get("valid", True):
            all_valid = False
            for w in data.get("validation", {}).get("warnings", []):
                all_warnings.append(f"[{category}] {w}")
    
    results["validation"] = {
        "valid": all_valid,
        "warnings": all_warnings
    }
    
    return results


def format_output(data: Dict[str, Any]) -> str:
    """Format results as human-readable text."""
    lines = []
    lines.append("")
    lines.append("═" * 75)
    
    category = data.get("category")
    if category:
        lines.append(f"📊 OPENROUTER AI MODEL RANKINGS - {category.upper()}")
    else:
        lines.append("📊 OPENROUTER AI MODEL RANKINGS")
    
    lines.append("═" * 75)
    lines.append(f"Source:   {data.get('source', 'N/A')}")
    lines.append(f"Method:   {data.get('method', 'N/A')}")
    lines.append(f"Time:     {data.get('timestamp', 'N/A')}")
    if category:
        lines.append(f"Category: {category}")
    
    validation = data.get("validation", {})
    if validation.get("valid"):
        lines.append("Status:   ✅ Valid")
    else:
        lines.append("Status:   ⚠️ Warnings")
    
    warnings = validation.get("warnings", [])
    if warnings:
        lines.append("")
        lines.append(f"⚠️  Warnings ({len(warnings)}):")
        for w in warnings:
            lines.append(f"   - {w}")
    
    # Category-specific leaderboard (if fetching a category)
    category_leaderboard = data.get("category_leaderboard", [])
    if category and category_leaderboard:
        lines.append("")
        lines.append("─" * 75)
        lines.append(f"📈 {category.upper()} LEADERBOARD (Token Usage)")
        lines.append("─" * 75)
        lines.append(f"{'#':<4} {'Model':<32} {'Provider':<12} {'Tokens':<10} {'Share':<8}")
        for entry in category_leaderboard[:15]:
            lines.append(
                f"{entry['rank']:<4} {entry['model'][:32]:<32} "
                f"{(entry.get('provider') or '-')[:12]:<12} "
                f"{entry['tokens']:<10} {entry.get('share') or '-':<8}"
            )
    
    # General Leaderboard (if not category-only or no category data)
    leaderboard = data.get("leaderboard", [])
    if leaderboard and (not category or not category_leaderboard):
        lines.append("")
        lines.append("─" * 75)
        lines.append("📈 GENERAL LLM LEADERBOARD (Token Usage This Week)")
        lines.append("─" * 75)
        lines.append(f"{'#':<4} {'Model':<32} {'Provider':<12} {'Tokens':<10} {'Share':<8}")
        for entry in leaderboard[:15]:
            lines.append(
                f"{entry['rank']:<4} {entry['model'][:32]:<32} "
                f"{(entry.get('provider') or '-')[:12]:<12} "
                f"{entry['tokens']:<10} {entry.get('share') or '-':<8}"
            )
    
    # Top Apps (only for non-category fetches)
    if not category:
        top_apps = data.get("top_apps", [])
        if top_apps:
            lines.append("")
            lines.append("─" * 75)
            lines.append("📱 TOP APPS")
            lines.append("─" * 75)
            lines.append(f"{'#':<4} {'App':<25} {'Tokens':<12} {'Description'}")
            for app in top_apps[:10]:
                desc = (app.get('description') or '')[:30]
                lines.append(
                    f"{app['rank']:<4} {app['app'][:25]:<25} "
                    f"{app['tokens']:<12} {desc}"
                )
    
    lines.append("")
    return "\n".join(lines)


def format_all_categories_output(data: Dict[str, Any]) -> str:
    """Format all-categories results as human-readable text."""
    lines = []
    lines.append("")
    lines.append("═" * 75)
    lines.append("📊 OPENROUTER AI MODEL RANKINGS - ALL CATEGORIES")
    lines.append("═" * 75)
    lines.append(f"Time:     {data.get('timestamp', 'N/A')}")
    
    validation = data.get("validation", {})
    if validation.get("valid"):
        lines.append("Status:   ✅ All Valid")
    else:
        lines.append("Status:   ⚠️ Some Warnings")
    
    warnings = validation.get("warnings", [])
    if warnings:
        lines.append("")
        lines.append(f"⚠️  Warnings ({len(warnings)}):")
        for w in warnings[:10]:  # Limit to first 10 warnings
            lines.append(f"   - {w}")
        if len(warnings) > 10:
            lines.append(f"   ... and {len(warnings) - 10} more")
    
    categories = data.get("categories", {})
    for cat_name, cat_data in categories.items():
        leaderboard = cat_data.get("leaderboard", [])
        lines.append("")
        lines.append("─" * 75)
        lines.append(f"📈 {cat_name.upper()} ({len(leaderboard)} models)")
        lines.append("─" * 75)
        
        if leaderboard:
            lines.append(f"{'#':<4} {'Model':<32} {'Provider':<12} {'Tokens':<10} {'Share':<8}")
            for entry in leaderboard[:5]:  # Top 5 for each category
                lines.append(
                    f"{entry['rank']:<4} {entry['model'][:32]:<32} "
                    f"{(entry.get('provider') or '-')[:12]:<12} "
                    f"{entry['tokens']:<10} {entry.get('share') or '-':<8}"
                )
        else:
            lines.append("  (no data)")
    
    lines.append("")
    return "\n".join(lines)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Fetch AI model rankings from OpenRouter.ai",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Fetch general LLM leaderboard and Top Apps
    docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py
    
    # Fetch with Programming category leaderboard (the only reliably available category)
    docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py --category programming
    
    # Output as JSON
    docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py --json
    
    # Save to file
    docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py --json -o /app/rankings.json
    
    # Basic mode (no Firecrawl API required, limited data)
    docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py --basic

IMPORTANT: OpenRouter's rankings page is a Single Page Application (SPA).
The script captures:
  - General LLM Leaderboard (top models by overall token usage)
  - Top Apps (largest public apps using OpenRouter)
  - Programming Category Leaderboard (when --category programming is used)

NOTE: Other categories (roleplay, legal, marketing, etc.) are NOT reliably available
because OpenRouter's SPA doesn't auto-select categories from the URL path.
The Categories section always defaults to showing "Programming" data.
"""
    )
    
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--output", "-o", help="Save output to file")
    parser.add_argument("--basic", action="store_true", help="Use basic HTML parsing (no Firecrawl)")
    parser.add_argument(
        "--category", "-c",
        choices=AVAILABLE_CATEGORIES,
        help="Fetch category-specific leaderboard. NOTE: Due to OpenRouter's SPA limitations, "
             "only 'programming' category data is reliably available."
    )
    
    args = parser.parse_args()
    
    # Fetch rankings
    data = await fetch_rankings(basic_mode=args.basic, category=args.category)
    if args.json:
        output = json.dumps(data, indent=2)
    else:
        output = format_output(data)
    
    # Output
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"✅ Output saved to {args.output}")
    else:
        print(output)
    
    # Exit with error code if validation failed
    if not data.get("validation", {}).get("valid", True):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
