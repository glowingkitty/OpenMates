#!/usr/bin/env python3
"""
Fetches AI model rankings from SimpleBench (simple-bench.com) using Firecrawl.

SimpleBench is a multiple-choice text benchmark where non-specialized humans
outperform frontier LLMs on spatio-temporal reasoning, social intelligence,
and linguistic adversarial robustness (trick questions).

This script:
1. Uses Firecrawl API (via Vault) to scrape the SimpleBench leaderboard page
2. Parses the markdown table (rank, model, score, organization)
3. Validates the output to detect when the scraper breaks
4. Outputs formatted text or JSON

Usage:
    docker exec -it api python /app/backend/scripts/fetch_simplebench_rankings.py
    docker exec -it api python /app/backend/scripts/fetch_simplebench_rankings.py --json
    docker exec -it api python /app/backend/scripts/fetch_simplebench_rankings.py -o /app/simplebench.json

Options:
    --json            Output as JSON instead of formatted text
    -o, --output FILE Save output to file
    --limit N         Max models to return (default: 100)
    --include-human   Include the human baseline in results

Note: This script is designed to run inside the Docker container where it has
access to Vault for the Firecrawl API key.
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
script_logger = logging.getLogger('fetch_simplebench_rankings')
script_logger.setLevel(logging.INFO)

# Suppress verbose logging from libraries
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

BASE_URL = "https://simple-bench.com/"

# Known providers/organizations for validation
KNOWN_PROVIDERS = {
    'anthropic', 'google', 'openai', 'meta', 'mistral', 'deepseek', 'alibaba',
    'cohere', 'xai', 'minimax', 'moonshot', 'moonshot ai', 'kimi ai', 'z.ai'
}

# Expected models in leaderboard (at least some should appear for validation)
EXPECTED_MODELS = [
    'gemini', 'claude', 'gpt', 'grok', 'llama', 'deepseek', 'qwen',
    'mistral', 'o1', 'o3', 'o4', 'sonnet', 'opus', 'flash'
]


# ═══════════════════════════════════════════════════════════════════════════════
# Parsing Functions
# ═══════════════════════════════════════════════════════════════════════════════

def parse_rank(rank_str: str) -> Optional[int]:
    """
    Parse rank string like '1st', '2nd', '23rd', '4th' into integer.
    Also handles '-' for human baseline.
    
    Args:
        rank_str: Rank string (e.g., '1st', '23rd', '-')
        
    Returns:
        Integer rank or None for special entries like human baseline
    """
    rank_str = rank_str.strip()
    
    # Human baseline marker
    if rank_str == '-':
        return None
    
    # Extract numeric part from strings like '1st', '2nd', '23rd', '4th'
    match = re.match(r'^(\d+)(?:st|nd|rd|th)?$', rank_str)
    if match:
        return int(match.group(1))
    
    return None


def parse_score(score_str: str) -> Optional[float]:
    """
    Parse score string like '76.4%' into float (as percentage value).
    
    Args:
        score_str: Score string (e.g., '76.4%', '41.7%')
        
    Returns:
        Float percentage value or None if parsing fails
    """
    score_str = score_str.strip()
    
    # Remove % sign and parse
    match = re.match(r'^([\d.]+)%$', score_str)
    if match:
        return float(match.group(1))
    
    return None


def parse_simplebench_markdown(markdown: str, include_human: bool = False) -> List[Dict[str, Any]]:
    """
    Parse SimpleBench leaderboard data from Firecrawl markdown output.
    
    The SimpleBench table format is:
    | Rank | Model | Score (AVG@5) | Organization |
    | --- | --- | --- | --- |
    | - | Human Baseline* | 83.7% |  |
    | 1st | Gemini 3 Pro Preview | 76.4% | Google |
    | 2nd | Claude Opus 4.5 | 62.0% | Anthropic |
    
    Args:
        markdown: Full markdown content from Firecrawl
        include_human: If True, include human baseline entry (rank=0)
        
    Returns:
        List of ranking dicts with rank, model, score, organization
    """
    rankings = []
    seen_models = set()
    
    # Find the Leaderboard section
    leaderboard_start = markdown.find("## Leaderboard")
    if leaderboard_start == -1:
        script_logger.warning("Could not find '## Leaderboard' section in markdown")
        leaderboard_start = 0
    
    # Look for next section to bound the search
    leaderboard_end = markdown.find("##", leaderboard_start + 20)
    if leaderboard_end == -1:
        leaderboard_end = len(markdown)
    
    leaderboard_section = markdown[leaderboard_start:leaderboard_end]
    
    # Process each line that looks like a table row
    for line in leaderboard_section.split('\n'):
        # Skip non-table lines and header/separator lines
        if not line.startswith('|'):
            continue
        if '---' in line:
            continue
        if 'Rank' in line and 'Model' in line:
            continue  # Skip header row
        
        # Split by |, filter empty parts
        parts = [p.strip() for p in line.split('|')]
        parts = [p for p in parts if p is not None]  # Keep empty strings for now
        
        # We expect 4 columns: Rank, Model, Score, Organization
        # But split gives us empty strings at start/end due to leading/trailing |
        parts = [p for p in parts if p != '']
        
        if len(parts) < 3:
            continue
        
        # Extract rank, model, score, organization
        rank_str = parts[0].strip()
        model = parts[1].strip() if len(parts) > 1 else None
        score_str = parts[2].strip() if len(parts) > 2 else None
        organization = parts[3].strip() if len(parts) > 3 else None
        
        if not model or not score_str:
            continue
        
        # Parse rank
        rank = parse_rank(rank_str)
        
        # Handle human baseline
        is_human = 'human' in model.lower()
        if is_human and not include_human:
            continue
        
        # Parse score
        score = parse_score(score_str)
        if score is None:
            continue
        
        # Validate score is in reasonable range (0-100%)
        if score < 0 or score > 100:
            continue
        
        # Clean model name (remove asterisks and escape chars)
        model = model.replace('\\*', '').replace('*', '').strip()
        
        # Skip duplicates
        model_key = model.lower()
        if model_key in seen_models:
            continue
        seen_models.add(model_key)
        
        entry = {
            "rank": rank if rank is not None else 0,  # Human baseline gets rank 0
            "model": model,
            "score": score,
        }
        
        if organization:
            entry["organization"] = organization
        
        rankings.append(entry)
    
    # Sort by rank (human baseline with rank 0 first, then by rank)
    rankings.sort(key=lambda x: (x.get("rank") or 0, x.get("score") or 0))
    
    return rankings


# ═══════════════════════════════════════════════════════════════════════════════
# Validation Functions
# ═══════════════════════════════════════════════════════════════════════════════

def validate_markdown_structure(markdown: str) -> List[str]:
    """
    Validate the raw markdown contains expected table structure.
    
    This helps detect when Firecrawl returns unexpected content (e.g., Cloudflare
    block page, error page, or completely different page structure).
    
    Args:
        markdown: Raw markdown content
        
    Returns:
        List of warning messages (empty if all validations pass)
    """
    warnings = []
    
    # Check for leaderboard section
    if "## Leaderboard" not in markdown and "Leaderboard" not in markdown:
        warnings.append("Missing 'Leaderboard' section header")
    
    # Check for table structure
    if "| Rank |" not in markdown and "|Rank|" not in markdown:
        warnings.append("Missing table header with 'Rank' column")
    
    # Check for SimpleBench-specific content
    if "SimpleBench" not in markdown:
        warnings.append("Missing 'SimpleBench' identifier - may be wrong page")
    
    # Check for at least one table row with scoring pattern
    score_pattern = r'\|\s*\d+(?:st|nd|rd|th)?\s*\|.*\|\s*\d+\.\d+%\s*\|'
    if not re.search(score_pattern, markdown):
        warnings.append("No valid table rows found with expected format")
    
    # Check for Cloudflare/bot block indicators
    cloudflare_indicators = [
        "Just a moment...",
        "Checking your browser",
        "cf-browser-verification",
        "403 Forbidden",
        "Access Denied"
    ]
    for indicator in cloudflare_indicators:
        if indicator.lower() in markdown.lower():
            warnings.append(f"Possible block page detected: '{indicator}'")
    
    return warnings


def validate_rankings(rankings: List[Dict[str, Any]]) -> List[str]:
    """
    Validate the parsed rankings for data quality.
    
    Args:
        rankings: List of parsed ranking entries
        
    Returns:
        List of warning messages (empty if all validations pass)
    """
    warnings = []
    
    if len(rankings) < 10:
        warnings.append(f"Only {len(rankings)} models found (expected 30+)")
    
    # Check for expected models
    found_models = set()
    for entry in rankings:
        model_lower = entry.get('model', '').lower()
        for expected in EXPECTED_MODELS:
            if expected in model_lower:
                found_models.add(expected)
    
    if len(found_models) < 3:
        warnings.append(
            f"Only found {len(found_models)}/10 expected model families: {found_models}"
        )
    
    # Check for organizations
    has_org = sum(1 for e in rankings if e.get('organization'))
    if has_org < len(rankings) * 0.5:
        warnings.append(
            f"Only {has_org}/{len(rankings)} entries have organization data"
        )
    
    # Check score distribution
    scores = [e.get('score', 0) for e in rankings if e.get('rank')]
    if scores:
        # SimpleBench scores range from ~10% to ~80%
        if max(scores) < 50:
            warnings.append(f"Max score {max(scores)}% seems too low")
        if min(scores) > 30:
            warnings.append(f"Min score {min(scores)}% seems too high")
    
    # Check for rank continuity
    ranks = sorted([e.get('rank') for e in rankings if e.get('rank')])
    if ranks and ranks[0] != 1:
        warnings.append(f"Rankings don't start at 1 (starts at {ranks[0]})")
    
    return warnings


# ═══════════════════════════════════════════════════════════════════════════════
# Output Formatting
# ═══════════════════════════════════════════════════════════════════════════════

def format_text_output(rankings: List[Dict[str, Any]]) -> str:
    """
    Format rankings as human-readable text.
    
    Args:
        rankings: List of ranking entries
        
    Returns:
        Formatted text string
    """
    lines = []
    lines.append("=" * 80)
    lines.append("SIMPLEBENCH LEADERBOARD - AI Reasoning Benchmark")
    lines.append("Source: https://simple-bench.com/")
    lines.append(f"Fetched: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"{'Rank':<6} {'Model':<40} {'Score':<12} {'Organization':<20}")
    lines.append("-" * 80)
    
    for entry in rankings:
        rank = entry.get('rank')
        rank_str = '-' if rank == 0 else f"#{rank}"
        model = entry.get('model', 'Unknown')[:38]
        score = entry.get('score', 0)
        score_str = f"{score:.1f}%"
        org = entry.get('organization', '')[:18]
        
        lines.append(f"{rank_str:<6} {model:<40} {score_str:<12} {org:<20}")
    
    lines.append("")
    lines.append(f"Total models: {len([e for e in rankings if e.get('rank')])}")
    lines.append("")
    lines.append("Note: Human baseline (83.7%) shows non-specialized humans outperform SOTA models.")
    lines.append("")
    
    return "\n".join(lines)


def create_json_output(rankings: List[Dict[str, Any]], warnings: List[str]) -> Dict[str, Any]:
    """
    Create structured JSON output with metadata.
    
    Args:
        rankings: List of ranking entries
        warnings: Any validation warnings
        
    Returns:
        JSON-serializable dictionary
    """
    return {
        "source": "SimpleBench",
        "url": BASE_URL,
        "description": "Multiple-choice text benchmark for LLM reasoning",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_models": len([e for e in rankings if e.get('rank')]),
        "human_baseline": next(
            (e.get('score') for e in rankings if e.get('rank') == 0),
            None
        ),
        "rankings": rankings,
        "warnings": warnings if warnings else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Main Execution
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_simplebench_rankings(
    limit: int = 100,
    include_human: bool = False
) -> tuple[List[Dict[str, Any]], List[str]]:
    """
    Fetch and parse SimpleBench rankings using Firecrawl.
    
    Args:
        limit: Maximum number of models to return
        include_human: Include human baseline in results
        
    Returns:
        Tuple of (rankings list, warnings list)
    """
    all_warnings = []
    
    script_logger.info("Fetching SimpleBench leaderboard...")
    script_logger.info(f"URL: {BASE_URL}")
    
    # Initialize SecretsManager for Vault access (Firecrawl API key)
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    
    try:
        # Use Firecrawl to scrape the page (handles JavaScript rendering)
        result = await scrape_url(
            url=BASE_URL,
            secrets_manager=secrets_manager,
            formats=["markdown"],
            only_main_content=True,
            sanitize_output=False  # Don't sanitize ranking data
        )
    finally:
        # Clean up SecretsManager
        await secrets_manager.aclose()
    
    # Check for Firecrawl errors
    if result.get("error"):
        raise RuntimeError(f"Firecrawl error: {result['error']}")
    
    # Extract markdown from result structure
    markdown = result.get("data", {}).get("markdown", "")
    
    if not markdown:
        raise RuntimeError("Firecrawl returned no markdown content")
    
    script_logger.info(f"Received {len(markdown)} characters of markdown")
    
    # Validate markdown structure
    struct_warnings = validate_markdown_structure(markdown)
    if struct_warnings:
        script_logger.warning(f"Markdown structure warnings: {struct_warnings}")
        all_warnings.extend(struct_warnings)
    
    # Parse the leaderboard
    rankings = parse_simplebench_markdown(markdown, include_human=include_human)
    script_logger.info(f"Parsed {len(rankings)} model rankings")
    
    # Validate parsed data
    data_warnings = validate_rankings(rankings)
    if data_warnings:
        script_logger.warning(f"Data validation warnings: {data_warnings}")
        all_warnings.extend(data_warnings)
    
    # Apply limit
    if limit and len(rankings) > limit:
        rankings = rankings[:limit]
    
    return rankings, all_warnings


def main():
    """Main entry point for command-line usage."""
    parser = argparse.ArgumentParser(
        description="Fetch AI model rankings from SimpleBench benchmark"
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON instead of formatted text'
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Save output to file'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=100,
        help='Maximum number of models to return (default: 100)'
    )
    parser.add_argument(
        '--include-human',
        action='store_true',
        help='Include human baseline in results'
    )
    
    args = parser.parse_args()
    
    try:
        # Run async fetch
        rankings, warnings = asyncio.run(
            fetch_simplebench_rankings(
                limit=args.limit,
                include_human=args.include_human
            )
        )
        
        if not rankings:
            script_logger.error("No rankings data retrieved")
            sys.exit(1)
        
        # Format output
        if args.json:
            output = json.dumps(
                create_json_output(rankings, warnings),
                indent=2,
                ensure_ascii=False
            )
        else:
            output = format_text_output(rankings)
            if warnings:
                output += "\nWarnings:\n" + "\n".join(f"  - {w}" for w in warnings)
        
        # Output to file or stdout
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output)
            script_logger.info(f"Output saved to {args.output}")
        else:
            print(output)
        
        # Exit with warning code if there were validation issues
        if warnings:
            script_logger.warning(f"Completed with {len(warnings)} warnings")
            sys.exit(0)  # Still success, but logged warnings
        
    except Exception as e:
        script_logger.error(f"Failed to fetch rankings: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
