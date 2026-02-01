#!/usr/bin/env python3
"""
Aggregates AI model rankings from multiple leaderboard sources.

This script:
1. Loads provider YAMLs to get external_ids mappings (lmarena, openrouter IDs)
2. Fetches rankings from LMArena and OpenRouter using existing fetch scripts
3. Merges data using external_ids to match models across sources
4. Normalizes scores to comparable 0-100 scale
5. Outputs aggregated leaderboard to backend/data/models_leaderboard.yml

Usage:
    docker exec -it api python /app/backend/scripts/aggregate_leaderboards.py
    docker exec -it api python /app/backend/scripts/aggregate_leaderboards.py --dry-run
    docker exec -it api python /app/backend/scripts/aggregate_leaderboards.py --category coding

Options:
    --dry-run         Print output instead of saving to file
    --category CAT    LMArena category (text, coding, math, etc.)
    --json            Output as JSON instead of YAML
    -o, --output FILE Custom output path

Note: This script is designed to run inside the Docker container where it has
access to Vault for API keys and provider YAML files.
"""

import asyncio
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# Add the backend directory to the Python path for imports
sys.path.insert(0, '/app/backend')

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

script_logger = logging.getLogger('aggregate_leaderboards')
script_logger.setLevel(logging.INFO)

# Suppress verbose logging from libraries
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

PROVIDERS_DIR = Path("/app/backend/providers")
OUTPUT_DIR = Path("/app/backend/data")
DEFAULT_OUTPUT_FILE = OUTPUT_DIR / "models_leaderboard.yml"

# LLM provider files (only those with AI models for chat)
LLM_PROVIDER_FILES = [
    "anthropic.yml",
    "openai.yml",
    "google.yml",
    "mistral.yml",
    "alibaba.yml",
    "zai.yml",
]

# Score normalization ranges
# LMArena Elo scores typically range from ~900 (poor) to ~1500 (top)
LMARENA_ELO_MIN = 900
LMARENA_ELO_MAX = 1500

# Task area category mappings from LMArena categories
TASK_AREA_CATEGORIES = {
    "code": ["coding", "code"],
    "math": ["math"],
    "creative": ["creative-writing", "writing"],
    "instruction": ["instruction-following", "hard-prompts"],
    "general": ["text", "overall"],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Provider YAML Loading
# ═══════════════════════════════════════════════════════════════════════════════

def load_provider_models() -> Dict[str, Dict[str, Any]]:
    """
    Load all models from provider YAML files.

    Returns:
        Dict mapping model_id -> model config including external_ids
    """
    models = {}

    for provider_file in LLM_PROVIDER_FILES:
        provider_path = PROVIDERS_DIR / provider_file
        if not provider_path.exists():
            script_logger.warning(f"Provider file not found: {provider_path}")
            continue

        try:
            with open(provider_path, 'r') as f:
                provider_config = yaml.safe_load(f)
        except Exception as e:
            script_logger.error(f"Failed to load {provider_file}: {e}")
            continue

        provider_id = provider_config.get("provider_id", "")
        provider_name = provider_config.get("name", "")

        for model in provider_config.get("models", []):
            model_id = model.get("id")
            if not model_id:
                continue

            models[model_id] = {
                "id": model_id,
                "name": model.get("name", model_id),
                "provider_id": provider_id,
                "provider_name": provider_name,
                "country_origin": model.get("country_origin"),
                "external_ids": model.get("external_ids", {}),
                "input_types": model.get("input_types", []),
                "output_types": model.get("output_types", []),
            }

    script_logger.info(f"Loaded {len(models)} models from provider YAMLs")
    return models


def build_external_id_index(models: Dict[str, Dict]) -> Dict[str, Dict[str, str]]:
    """
    Build reverse index from external IDs to our model IDs.

    Args:
        models: Dict mapping model_id -> model config

    Returns:
        Dict with keys 'lmarena', 'openrouter' mapping external IDs to our model IDs
    """
    index = {
        "lmarena": {},
        "openrouter": {},
    }

    for model_id, model_config in models.items():
        external_ids = model_config.get("external_ids", {})

        if "lmarena" in external_ids:
            lmarena_id = external_ids["lmarena"].lower()
            index["lmarena"][lmarena_id] = model_id

        if "openrouter" in external_ids:
            openrouter_id = external_ids["openrouter"].lower()
            index["openrouter"][openrouter_id] = model_id

    script_logger.info(
        f"Built external ID index: {len(index['lmarena'])} LMArena, "
        f"{len(index['openrouter'])} OpenRouter mappings"
    )
    return index


# ═══════════════════════════════════════════════════════════════════════════════
# Leaderboard Fetching
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_lmarena_data(category: str = "text") -> Dict[str, Any]:
    """
    Fetch LMArena rankings using the existing fetch script.

    Args:
        category: LMArena category (text, coding, math, etc.)

    Returns:
        Dict with rankings data
    """
    # Import the fetch function from the existing script
    try:
        from backend.scripts.fetch_lmarena_rankings import fetch_lmarena_rankings
    except ImportError:
        script_logger.error("Could not import fetch_lmarena_rankings")
        return {"rankings": [], "validation": {"valid": False}}

    script_logger.info(f"Fetching LMArena rankings (category: {category})...")

    try:
        data = await fetch_lmarena_rankings(category=category, limit=100)
        script_logger.info(f"LMArena returned {len(data.get('rankings', []))} models")
        return data
    except Exception as e:
        script_logger.error(f"Failed to fetch LMArena data: {e}")
        return {"rankings": [], "validation": {"valid": False, "warnings": [str(e)]}}


async def fetch_openrouter_data(category: str = None) -> Dict[str, Any]:
    """
    Fetch OpenRouter rankings using the existing fetch script.

    Args:
        category: Optional category (programming, etc.)

    Returns:
        Dict with rankings data
    """
    try:
        from backend.scripts.fetch_openrouter_rankings import fetch_rankings
    except ImportError:
        script_logger.error("Could not import fetch_openrouter_rankings")
        return {"leaderboard": [], "validation": {"valid": False}}

    script_logger.info(f"Fetching OpenRouter rankings...")

    try:
        data = await fetch_rankings(basic_mode=False, category=category)
        script_logger.info(f"OpenRouter returned {len(data.get('leaderboard', []))} models")
        return data
    except Exception as e:
        script_logger.error(f"Failed to fetch OpenRouter data: {e}")
        return {"leaderboard": [], "validation": {"valid": False, "warnings": [str(e)]}}


# ═══════════════════════════════════════════════════════════════════════════════
# Score Normalization
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_elo_score(elo: int, min_elo: int = LMARENA_ELO_MIN, max_elo: int = LMARENA_ELO_MAX) -> float:
    """
    Normalize Elo score to 0-100 scale.

    Args:
        elo: Raw Elo score (e.g., 1489)
        min_elo: Minimum Elo for 0 score
        max_elo: Maximum Elo for 100 score

    Returns:
        Normalized score 0-100
    """
    if elo <= min_elo:
        return 0.0
    if elo >= max_elo:
        return 100.0

    return round((elo - min_elo) / (max_elo - min_elo) * 100, 1)


def normalize_rank_to_score(rank: int, total: int) -> float:
    """
    Convert rank position to a score (higher rank = higher score).

    Args:
        rank: Position (1 = best)
        total: Total number of ranked items

    Returns:
        Normalized score 0-100
    """
    if total <= 1:
        return 100.0

    # Rank 1 = 100, last rank = 0
    return round((total - rank) / (total - 1) * 100, 1)


def parse_tokens_str(tokens_str: str) -> int:
    """
    Parse token count string like '582B', '1.2T', '50M' to integer.

    Args:
        tokens_str: Token string with suffix

    Returns:
        Token count as integer
    """
    if not tokens_str:
        return 0

    tokens_str = tokens_str.strip().upper()

    multipliers = {
        'K': 1_000,
        'M': 1_000_000,
        'B': 1_000_000_000,
        'T': 1_000_000_000_000,
    }

    for suffix, mult in multipliers.items():
        if tokens_str.endswith(suffix):
            try:
                return int(float(tokens_str[:-1]) * mult)
            except ValueError:
                return 0

    try:
        return int(float(tokens_str))
    except ValueError:
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
# Data Merging
# ═══════════════════════════════════════════════════════════════════════════════

def match_lmarena_model(
    lmarena_entry: Dict,
    external_index: Dict[str, Dict[str, str]]
) -> Optional[str]:
    """
    Try to match an LMArena entry to our model ID.

    Args:
        lmarena_entry: LMArena ranking entry
        external_index: Index of external IDs to our model IDs

    Returns:
        Our model_id if matched, None otherwise
    """
    model_name = lmarena_entry.get("model", "").lower()

    # Direct lookup in lmarena index
    if model_name in external_index["lmarena"]:
        return external_index["lmarena"][model_name]

    # Try partial matching for common patterns
    for lmarena_id, our_id in external_index["lmarena"].items():
        # Handle variations like "claude-4.5-sonnet" vs "claude-sonnet-4-5"
        if lmarena_id in model_name or model_name in lmarena_id:
            return our_id

    return None


def match_openrouter_model(
    openrouter_entry: Dict,
    external_index: Dict[str, Dict[str, str]]
) -> Optional[str]:
    """
    Try to match an OpenRouter entry to our model ID.

    Args:
        openrouter_entry: OpenRouter ranking entry
        external_index: Index of external IDs to our model IDs

    Returns:
        Our model_id if matched, None otherwise
    """
    slug = openrouter_entry.get("slug", "").lower()

    # Direct lookup in openrouter index
    if slug in external_index["openrouter"]:
        return external_index["openrouter"][slug]

    # Try matching by provider/model pattern
    for openrouter_id, our_id in external_index["openrouter"].items():
        if openrouter_id in slug or slug in openrouter_id:
            return our_id

    return None


def merge_leaderboard_data(
    our_models: Dict[str, Dict],
    external_index: Dict[str, Dict[str, str]],
    lmarena_data: Dict[str, Any],
    openrouter_data: Dict[str, Any],
    category: str = "general"
) -> List[Dict[str, Any]]:
    """
    Merge leaderboard data from multiple sources.

    Args:
        our_models: Dict of our model configs
        external_index: Index mapping external IDs to our model IDs
        lmarena_data: LMArena rankings data
        openrouter_data: OpenRouter rankings data
        category: Task area category

    Returns:
        List of merged model rankings
    """
    # Initialize merged data for each of our models
    merged = {}

    for model_id, model_config in our_models.items():
        merged[model_id] = {
            "model_id": model_id,
            "name": model_config.get("name"),
            "provider_id": model_config.get("provider_id"),
            "provider_name": model_config.get("provider_name"),
            "country_origin": model_config.get("country_origin"),
            "scores": {},
            "raw_data": {},
        }

    # Process LMArena data
    lmarena_rankings = lmarena_data.get("rankings", [])
    lmarena_matched = 0

    for entry in lmarena_rankings:
        our_model_id = match_lmarena_model(entry, external_index)
        if our_model_id and our_model_id in merged:
            elo = entry.get("score", 0)
            normalized = normalize_elo_score(elo)

            merged[our_model_id]["scores"]["lmarena_elo"] = elo
            merged[our_model_id]["scores"]["lmarena_normalized"] = normalized
            merged[our_model_id]["raw_data"]["lmarena_rank"] = entry.get("rank")
            merged[our_model_id]["raw_data"]["lmarena_votes"] = entry.get("votes")
            merged[our_model_id]["raw_data"]["lmarena_org"] = entry.get("organization")
            lmarena_matched += 1

    script_logger.info(f"Matched {lmarena_matched}/{len(lmarena_rankings)} LMArena models")

    # Process OpenRouter data
    openrouter_leaderboard = openrouter_data.get("leaderboard", [])
    openrouter_matched = 0
    total_openrouter = len(openrouter_leaderboard)

    for entry in openrouter_leaderboard:
        our_model_id = match_openrouter_model(entry, external_index)
        if our_model_id and our_model_id in merged:
            rank = entry.get("rank", 0)
            tokens = parse_tokens_str(entry.get("tokens", "0"))
            rank_score = normalize_rank_to_score(rank, total_openrouter)

            merged[our_model_id]["scores"]["openrouter_rank"] = rank
            merged[our_model_id]["scores"]["openrouter_rank_score"] = rank_score
            merged[our_model_id]["raw_data"]["openrouter_tokens"] = tokens
            merged[our_model_id]["raw_data"]["openrouter_share"] = entry.get("share")
            openrouter_matched += 1

    script_logger.info(f"Matched {openrouter_matched}/{len(openrouter_leaderboard)} OpenRouter models")

    # Calculate composite score
    for model_id, data in merged.items():
        scores = data["scores"]

        # Weighted average of available scores
        # LMArena Elo is more representative of quality, so weight it higher
        lmarena_score = scores.get("lmarena_normalized", 0)
        openrouter_score = scores.get("openrouter_rank_score", 0)

        # If we have both scores, use weighted average (60% LMArena, 40% OpenRouter)
        # If only one score, use that score
        if lmarena_score > 0 and openrouter_score > 0:
            composite = lmarena_score * 0.6 + openrouter_score * 0.4
        elif lmarena_score > 0:
            composite = lmarena_score
        elif openrouter_score > 0:
            composite = openrouter_score
        else:
            composite = 0

        data["scores"]["composite"] = round(composite, 1)

    # Convert to list and sort by composite score
    result = list(merged.values())
    result.sort(key=lambda x: x["scores"].get("composite", 0), reverse=True)

    # Add final rank
    for i, entry in enumerate(result, 1):
        entry["rank"] = i

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Output Generation
# ═══════════════════════════════════════════════════════════════════════════════

def generate_output(
    rankings: List[Dict],
    lmarena_data: Dict,
    openrouter_data: Dict,
    category: str
) -> Dict[str, Any]:
    """
    Generate the final output structure.

    Args:
        rankings: Merged and sorted rankings
        lmarena_data: Original LMArena data for metadata
        openrouter_data: Original OpenRouter data for metadata
        category: Task area category

    Returns:
        Output dict ready for YAML/JSON serialization
    """
    # Filter to only models with scores
    ranked_models = [r for r in rankings if r["scores"].get("composite", 0) > 0]
    unranked_models = [r for r in rankings if r["scores"].get("composite", 0) == 0]

    output = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "sources": {
                "lmarena": {
                    "url": lmarena_data.get("source", ""),
                    "category": lmarena_data.get("category", ""),
                    "models_fetched": len(lmarena_data.get("rankings", [])),
                    "valid": lmarena_data.get("validation", {}).get("valid", False),
                },
                "openrouter": {
                    "url": openrouter_data.get("source", ""),
                    "models_fetched": len(openrouter_data.get("leaderboard", [])),
                    "valid": openrouter_data.get("validation", {}).get("valid", False),
                },
            },
            "total_models": len(rankings),
            "ranked_models": len(ranked_models),
            "unranked_models": len(unranked_models),
        },
        "rankings": [],
        "unranked": [],
    }

    # Add ranked models (simplified structure for the output)
    for entry in ranked_models:
        output["rankings"].append({
            "rank": entry["rank"],
            "model_id": entry["model_id"],
            "name": entry["name"],
            "provider_id": entry["provider_id"],
            "country_origin": entry["country_origin"],
            "composite_score": entry["scores"]["composite"],
            "lmarena_elo": entry["scores"].get("lmarena_elo"),
            "lmarena_rank": entry["raw_data"].get("lmarena_rank"),
            "openrouter_rank": entry["scores"].get("openrouter_rank"),
        })

    # Add unranked models (no external data available)
    for entry in unranked_models:
        output["unranked"].append({
            "model_id": entry["model_id"],
            "name": entry["name"],
            "provider_id": entry["provider_id"],
            "country_origin": entry["country_origin"],
        })

    return output


def save_output(output: Dict, output_path: Path, as_json: bool = False) -> None:
    """
    Save output to file.

    Args:
        output: Output dict to save
        output_path: Path to save to
        as_json: Save as JSON instead of YAML
    """
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        if as_json:
            json.dump(output, f, indent=2, ensure_ascii=False)
        else:
            yaml.dump(output, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    script_logger.info(f"Saved output to {output_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

async def aggregate_leaderboards(
    category: str = "text",
    output_path: Optional[Path] = None,
    dry_run: bool = False,
    as_json: bool = False
) -> Dict[str, Any]:
    """
    Main aggregation function.

    Args:
        category: LMArena category to fetch
        output_path: Custom output path (default: backend/data/models_leaderboard.yml)
        dry_run: If True, don't save to file
        as_json: Output as JSON instead of YAML

    Returns:
        Aggregated leaderboard data
    """
    script_logger.info("Starting leaderboard aggregation...")

    # Step 1: Load provider models and build index
    our_models = load_provider_models()
    external_index = build_external_id_index(our_models)

    # Step 2: Fetch data from both sources
    lmarena_data = await fetch_lmarena_data(category=category)
    openrouter_data = await fetch_openrouter_data()

    # Step 3: Merge and normalize data
    task_area = "general"
    for area, categories in TASK_AREA_CATEGORIES.items():
        if category.lower() in categories:
            task_area = area
            break

    rankings = merge_leaderboard_data(
        our_models,
        external_index,
        lmarena_data,
        openrouter_data,
        category=task_area
    )

    # Step 4: Generate output
    output = generate_output(rankings, lmarena_data, openrouter_data, task_area)

    # Step 5: Save or print
    if dry_run:
        if as_json:
            print(json.dumps(output, indent=2, ensure_ascii=False))
        else:
            print(yaml.dump(output, default_flow_style=False, allow_unicode=True, sort_keys=False))
    else:
        path = output_path or DEFAULT_OUTPUT_FILE
        save_output(output, path, as_json=as_json)
        print(f"✅ Leaderboard aggregated and saved to {path}")

    return output


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Aggregate AI model rankings from multiple leaderboard sources",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run inside Docker
    docker exec -it api python /app/backend/scripts/aggregate_leaderboards.py
    docker exec -it api python /app/backend/scripts/aggregate_leaderboards.py --dry-run
    docker exec -it api python /app/backend/scripts/aggregate_leaderboards.py --category coding
    docker exec -it api python /app/backend/scripts/aggregate_leaderboards.py --json -o /app/rankings.json

Categories (LMArena): text, coding, math, creative-writing, instruction-following, etc.
Output: backend/data/models_leaderboard.yml (default)
        """
    )
    parser.add_argument("--category", "-c", default="text", help="LMArena category (default: text)")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Print output instead of saving")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON instead of YAML")
    parser.add_argument("--output", "-o", help="Custom output file path")

    args = parser.parse_args()

    output_path = Path(args.output) if args.output else None

    asyncio.run(aggregate_leaderboards(
        category=args.category,
        output_path=output_path,
        dry_run=args.dry_run,
        as_json=args.json
    ))


if __name__ == "__main__":
    main()
