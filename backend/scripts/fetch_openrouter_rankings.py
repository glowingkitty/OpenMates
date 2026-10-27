#!/usr/bin/env python3
"""Offline parsing utilities for saved leaderboard data. Live collection is unavailable."""

import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Add the backend directory to the Python path for imports
sys.path.insert(0, '/app/backend')


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



# ═══════════════════════════════════════════════════════════════════════════════
# Parsing Functions
# ═══════════════════════════════════════════════════════════════════════════════

def parse_leaderboard(markdown_content: str) -> List[Dict[str, Any]]:
    """
    Parse the LLM Leaderboard section from saved markdown.
    
    Format (multi-line entries, may include favicon images):
    ```
    1.
    ![Favicon for google](https://openrouter.ai/images/icons/GoogleGemini.svg)
    [Gemini 3.5 Flash](https://openrouter.ai/google/gemini-3.5-flash)
    by [google](https://openrouter.ai/google)
    764B tokens
    40%
    ```
    
    Args:
        markdown_content: Saved markdown content
        
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
    Parse the Top Apps section from saved markdown.
    
    Args:
        markdown_content: Saved markdown content
        
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
        markdown_content: Saved markdown content
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
    Parse basic HTML for the leaderboard (offline input only).
    
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
    """Report unavailable collection without credentials or outbound requests."""
    raise RuntimeError("No supported leaderboard data source is configured.")


async def fetch_all_categories(basic_mode: bool = False) -> Dict[str, Any]:
    """
    Fetch rankings for all available categories.
    
    Args:
        basic_mode: Legacy argument; live collection remains unavailable.
        
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
    raise SystemExit("No supported leaderboard data source is configured.")


if __name__ == "__main__":
    asyncio.run(main())
