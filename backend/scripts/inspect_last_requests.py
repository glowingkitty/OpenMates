#!/usr/bin/env python3
"""
Script to inspect the last 10 AI request debug data including preprocessor, main processor,
and postprocessor input/output for debugging purposes.

This script:
1. Fetches the cached debug request entries from Dragonfly (encrypted)
2. Decrypts the entries using the DEBUG_REQUESTS_ENCRYPTION_KEY (Vault)
3. Optionally filters by chat_id
4. Saves the FULL debug data to a YAML file for analysis

ARCHITECTURE:
- Debug entries are stored as an encrypted list in Dragonfly with 30-minute TTL
- Each entry contains complete input/output for all three processor stages
- Entries are stored globally (not per user) with a max of 10 entries
- Data is encrypted server-side with DEBUG_REQUESTS_ENCRYPTION_KEY

OUTPUT:
- Saves to /app/backend/scripts/debug_output/last_requests_<timestamp>.yml
- Contains FULL content of all processor inputs/outputs for debugging

Usage:
    # Save all recent requests to YAML
    docker exec -it api python /app/backend/scripts/inspect_last_requests.py
    
    # Filter by chat ID
    docker exec -it api python /app/backend/scripts/inspect_last_requests.py --chat-id abc12345-6789-0123-4567-890123456789
    
    # Specify custom output file
    docker exec -it api python /app/backend/scripts/inspect_last_requests.py --output /tmp/debug.yml
"""

import asyncio
import argparse
import logging
import sys
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')

# Try to import yaml - use ruamel.yaml if available, otherwise PyYAML
try:
    from ruamel.yaml import YAML
    USE_RUAMEL = True
except ImportError:
    import yaml
    USE_RUAMEL = False

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService

# Configure logging
logging.basicConfig(
    level=logging.WARNING,  # Only show warnings and errors from libraries
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Set our script logger to INFO level
script_logger = logging.getLogger('inspect_last_requests')
script_logger.setLevel(logging.INFO)

# Suppress verbose logging from httpx and other libraries
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)

# Default output directory
DEFAULT_OUTPUT_DIR = "/app/backend/scripts/debug_output"


def format_timestamp(ts: Optional[int]) -> str:
    """
    Format a Unix timestamp to human-readable string.
    
    Args:
        ts: Unix timestamp in seconds or None
        
    Returns:
        Formatted datetime string or "N/A" if timestamp is None/invalid
    """
    if not ts:
        return "N/A"
    try:
        if isinstance(ts, int):
            dt = datetime.fromtimestamp(ts)
        else:
            # Try parsing as ISO format string
            dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def prepare_yaml_output(
    entries: List[Dict[str, Any]],
    chat_id_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Prepare the debug data structure for YAML output.
    
    Entries are sorted chronologically (oldest first) so you can follow
    the request flow in order: request 1 → request 2 → request 3, etc.
    
    Args:
        entries: List of debug request entries (FULL content)
        chat_id_filter: Optional chat ID filter that was applied
        
    Returns:
        Dictionary ready for YAML serialization
    """
    # Sort entries chronologically (oldest first) by timestamp
    # This makes it easier to follow the request flow in order
    sorted_entries = sorted(entries, key=lambda e: e.get('timestamp', 0))
    
    # Add metadata
    output = {
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'generated_at_readable': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'chat_id_filter': chat_id_filter,
            'total_entries': len(sorted_entries),
            'note': 'This file contains FULL debug data for AI request processing. Entries are sorted chronologically (oldest first). Data auto-expires after 30 minutes in cache.',
        },
        'requests': []
    }
    
    # Process each entry (now in chronological order)
    for i, entry in enumerate(sorted_entries, 1):
        request_data = {
            'request_number': i,
            'task_id': entry.get('task_id'),
            'chat_id': entry.get('chat_id'),
            'timestamp': entry.get('timestamp'),
            'timestamp_readable': format_timestamp(entry.get('timestamp')),
            
            # FULL preprocessor data
            'preprocessor': {
                'input': entry.get('preprocessor_input'),
                'output': entry.get('preprocessor_output'),
            },
            
            # FULL main processor data
            'main_processor': {
                'input': entry.get('main_processor_input'),
                'output': entry.get('main_processor_output'),
            },
            
            # FULL postprocessor data
            'postprocessor': {
                'input': entry.get('postprocessor_input'),
                'output': entry.get('postprocessor_output'),
            },
        }
        output['requests'].append(request_data)
    
    return output


def save_to_yaml(data: Dict[str, Any], output_path: str) -> str:
    """
    Save data to a YAML file.
    
    Args:
        data: Dictionary to save
        output_path: Path to save the YAML file
        
    Returns:
        The actual path where the file was saved
    """
    # Ensure the output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        script_logger.info(f"Created output directory: {output_dir}")
    
    if USE_RUAMEL:
        # Use ruamel.yaml for better formatting
        yaml_handler = YAML()
        yaml_handler.default_flow_style = False
        yaml_handler.width = 200  # Wider lines for readability
        yaml_handler.preserve_quotes = True
        
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml_handler.dump(data, f)
    else:
        # Fallback to PyYAML
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                width=200,
                sort_keys=False
            )
    
    return output_path


async def main():
    """Main function that inspects debug request entries and saves to YAML."""
    parser = argparse.ArgumentParser(
        description='Inspect the last 10 AI request debug entries and save to YAML file'
    )
    parser.add_argument(
        '--chat-id',
        type=str,
        default=None,
        help='Filter by chat ID'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=None,
        help='Output file path (default: debug_output/last_requests_<timestamp>.yml)'
    )
    
    args = parser.parse_args()
    
    script_logger.info("Starting debug request inspection...")
    
    # Initialize services
    cache_service = CacheService()
    encryption_service = EncryptionService(
        cache_service=cache_service
    )
    
    try:
        # Ensure cache client is connected
        await cache_service.client
        
        # Get debug entries
        if args.chat_id:
            # Filter by chat ID
            entries = await cache_service.get_debug_requests_for_chat(
                encryption_service=encryption_service,
                chat_id=args.chat_id
            )
            script_logger.info(f"Retrieved {len(entries)} debug entries for chat_id: {args.chat_id}")
        else:
            # Get all entries
            entries = await cache_service.get_all_debug_requests(
                encryption_service=encryption_service
            )
            script_logger.info(f"Retrieved {len(entries)} total debug entries")
        
        # Check if we have any entries
        if not entries:
            script_logger.warning("No debug request entries found.")
            script_logger.info("Note: Debug entries expire after 30 minutes.")
            script_logger.info("Make sure you have sent recent requests to the AI.")
            return
        
        # Prepare YAML output with FULL content
        yaml_data = prepare_yaml_output(entries, args.chat_id)
        
        # Determine output path
        if args.output:
            output_path = args.output
        else:
            # Generate timestamped filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            chat_suffix = f"_chat_{args.chat_id[:8]}" if args.chat_id else ""
            filename = f"last_requests_{timestamp}{chat_suffix}.yml"
            output_path = os.path.join(DEFAULT_OUTPUT_DIR, filename)
        
        # Save to YAML file
        saved_path = save_to_yaml(yaml_data, output_path)
        
        script_logger.info("=" * 60)
        script_logger.info("DEBUG DATA SAVED SUCCESSFULLY")
        script_logger.info("=" * 60)
        script_logger.info(f"Output file: {saved_path}")
        script_logger.info(f"Total entries: {len(entries)}")
        if args.chat_id:
            script_logger.info(f"Filtered by chat_id: {args.chat_id}")
        script_logger.info("=" * 60)
        script_logger.info("")
        script_logger.info("To view the file:")
        script_logger.info(f"  cat {saved_path}")
        script_logger.info("")
        script_logger.info("To copy to host machine:")
        script_logger.info(f"  docker cp api:{saved_path} ./debug_output.yml")
        script_logger.info("")
        
    except Exception as e:
        script_logger.error(f"Error during inspection: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
