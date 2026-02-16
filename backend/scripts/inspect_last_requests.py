#!/usr/bin/env python3
"""
Script to inspect admin AI request debug data including preprocessor, main processor,
and postprocessor input/output for debugging purposes.

This script:
1. Fetches the cached debug request entries from Dragonfly (encrypted)
2. Decrypts the entries using the DEBUG_REQUESTS_ENCRYPTION_KEY (Vault)
3. Provides multiple viewing modes: list, summary, or full YAML output
4. Supports filtering by chat_id, task_id, and time range

ARCHITECTURE:
- Only admin user requests are cached (regular users are never cached)
- Debug entries are stored as an encrypted list in Dragonfly with 72-hour TTL
- Each entry contains complete input/output for all three processor stages
- Entries are stored globally (admin users only) with a max of 50 entries
- Data is encrypted server-side with DEBUG_REQUESTS_ENCRYPTION_KEY

OUTPUT MODES:
- --list: Quick overview of available requests (default if no output file)
- --summary: Detailed summary with key metrics and error detection
- --yaml: Save FULL debug data to YAML file for deep analysis

Usage:
    # List all available requests (quick overview)
    docker exec -it api python /app/backend/scripts/inspect_last_requests.py --list
    
    # Show detailed summary with statistics
    docker exec -it api python /app/backend/scripts/inspect_last_requests.py --summary
    
    # Filter by chat ID and show list
    docker exec -it api python /app/backend/scripts/inspect_last_requests.py --chat-id abc123 --list
    
    # Filter by task ID
    docker exec -it api python /app/backend/scripts/inspect_last_requests.py --task-id celery-task-123
    
    # Filter by time (last 5 minutes)
    docker exec -it api python /app/backend/scripts/inspect_last_requests.py --since-minutes 5 --list
    
    # Save full YAML output
    docker exec -it api python /app/backend/scripts/inspect_last_requests.py --yaml --output /tmp/debug.yml
    
    # Show only requests with errors
    docker exec -it api python /app/backend/scripts/inspect_last_requests.py --errors-only
    
    # Clear all debug cache entries
    docker exec -it api python /app/backend/scripts/inspect_last_requests.py --clear
    
    # JSON output for programmatic use
    docker exec -it api python /app/backend/scripts/inspect_last_requests.py --json
"""

import asyncio
import argparse
import logging
import sys
import os
import json as json_module
import time
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


def format_duration(seconds: float) -> str:
    """
    Format a duration in seconds to human-readable string.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted duration string (e.g., "5m 30s", "45s", "2m")
    """
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)
    if remaining_seconds > 0:
        return f"{minutes}m {remaining_seconds}s"
    return f"{minutes}m"


def has_error_in_data(data: Any) -> bool:
    """
    Recursively check if data contains error indicators.
    
    Args:
        data: Data structure to check (dict, list, or primitive)
        
    Returns:
        True if error indicators found, False otherwise
    """
    if isinstance(data, dict):
        # Check for common error keys
        if 'error' in data or 'error_message' in data or 'exception' in data:
            return True
        # Check for status/success indicators
        if data.get('status') == 'error' or data.get('success') is False:
            return True
        # Recursively check nested dicts
        return any(has_error_in_data(v) for v in data.values())
    elif isinstance(data, list):
        # Recursively check list items
        return any(has_error_in_data(item) for item in data)
    elif isinstance(data, str):
        # Check for error keywords in strings (case-insensitive)
        error_keywords = ['exception', 'traceback', 'failed', 'error:']
        return any(keyword in data.lower() for keyword in error_keywords)
    return False


def extract_key_info(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract key information from a debug entry for summary display.
    
    Args:
        entry: Full debug entry
        
    Returns:
        Dictionary with key information extracted
    """
    info = {
        'task_id': entry.get('task_id', 'N/A'),
        'chat_id': entry.get('chat_id', 'N/A'),
        'timestamp': entry.get('timestamp'),
        'has_error': False,
        'stages_completed': [],
        'model_used': None,
        'tokens_used': None,
        'message_count': None,
    }
    
    # Check which stages have data
    if entry.get('preprocessor_output'):
        info['stages_completed'].append('preprocessor')
        # Extract message count from preprocessor
        preproc_out = entry.get('preprocessor_output', {})
        if isinstance(preproc_out, dict):
            messages = preproc_out.get('messages', [])
            if messages:
                info['message_count'] = len(messages)
    
    if entry.get('main_processor_output'):
        info['stages_completed'].append('main_processor')
        # Extract model info from main processor
        main_out = entry.get('main_processor_output', {})
        if isinstance(main_out, dict):
            # Try to extract model name
            model = (main_out.get('model') or 
                    main_out.get('response', {}).get('model') or
                    main_out.get('result', {}).get('model'))
            if model:
                info['model_used'] = model
            
            # Try to extract token usage
            usage = (main_out.get('usage') or
                    main_out.get('response', {}).get('usage') or
                    main_out.get('result', {}).get('usage'))
            if usage and isinstance(usage, dict):
                total = usage.get('total_tokens') or usage.get('total')
                if total:
                    info['tokens_used'] = total
    
    if entry.get('postprocessor_output'):
        info['stages_completed'].append('postprocessor')
    
    # Check for errors in any stage
    for stage in ['preprocessor', 'main_processor', 'postprocessor']:
        for data_type in ['input', 'output']:
            key = f"{stage}_{data_type}"
            if has_error_in_data(entry.get(key)):
                info['has_error'] = True
                break
        if info['has_error']:
            break
    
    return info


def print_list_view(entries: List[Dict[str, Any]]):
    """
    Print a concise list view of debug entries.
    
    Args:
        entries: List of debug entries (sorted chronologically)
    """
    if not entries:
        print("\n❌ No debug entries found.\n")
        return
    
    print("\n" + "=" * 100)
    print("DEBUG REQUEST ENTRIES (Chronological Order - Oldest First)")
    print("=" * 100)
    print(f"{'#':<3} {'Timestamp':<20} {'Task ID':<20} {'Chat ID':<20} {'Stages':<15} {'Status':<8}")
    print("-" * 100)
    
    for i, entry in enumerate(entries, 1):
        info = extract_key_info(entry)
        timestamp_str = format_timestamp(info['timestamp'])
        task_id = info['task_id'][:18] + '…' if len(info['task_id']) > 19 else info['task_id']
        chat_id = info['chat_id'][:18] + '…' if len(info['chat_id']) > 19 else info['chat_id']
        stages = '/'.join(s[0].upper() for s in info['stages_completed']) or 'None'
        status = '❌ ERROR' if info['has_error'] else '✅ OK'
        
        print(f"{i:<3} {timestamp_str:<20} {task_id:<20} {chat_id:<20} {stages:<15} {status:<8}")
    
    print("=" * 100)
    print(f"Total entries: {len(entries)} | Stages: P=Preprocessor, M=MainProcessor, P=Postprocessor")
    print("=" * 100 + "\n")


def print_summary_view(entries: List[Dict[str, Any]]):
    """
    Print a detailed summary view with statistics.
    
    Args:
        entries: List of debug entries
    """
    if not entries:
        print("\n❌ No debug entries found.\n")
        return
    
    # Calculate statistics
    total_entries = len(entries)
    entries_with_errors = sum(1 for e in entries if extract_key_info(e)['has_error'])
    
    # Time range
    timestamps = [e.get('timestamp', 0) for e in entries if e.get('timestamp')]
    if timestamps:
        oldest = min(timestamps)
        newest = max(timestamps)
        time_span = newest - oldest
        oldest_str = format_timestamp(oldest)
        newest_str = format_timestamp(newest)
        span_str = format_duration(time_span)
    else:
        oldest_str = newest_str = span_str = "N/A"
    
    # Chat distribution
    chat_ids = [e.get('chat_id') for e in entries if e.get('chat_id')]
    unique_chats = len(set(chat_ids))
    
    # Model usage
    models_used = []
    total_tokens = 0
    for e in entries:
        info = extract_key_info(e)
        if info['model_used']:
            models_used.append(info['model_used'])
        if info['tokens_used']:
            total_tokens += info['tokens_used']
    
    unique_models = set(models_used)
    
    # Print summary
    print("\n" + "=" * 80)
    print("DEBUG REQUEST SUMMARY")
    print("=" * 80)
    print(f"Total Entries:        {total_entries}")
    print(f"Entries with Errors:  {entries_with_errors} ({entries_with_errors/total_entries*100:.1f}%)" if total_entries > 0 else "Entries with Errors:  0")
    print(f"Unique Chats:         {unique_chats}")
    print(f"Time Range:           {oldest_str} → {newest_str} (span: {span_str})")
    if unique_models:
        print(f"Models Used:          {', '.join(unique_models)}")
        print(f"Total Tokens:         {total_tokens:,}")
    print("=" * 80)
    
    # Print detailed entry info
    print("\nDETAILED ENTRIES:\n")
    for i, entry in enumerate(entries, 1):
        info = extract_key_info(entry)
        print(f"{'─' * 80}")
        print(f"Request #{i}")
        print(f"{'─' * 80}")
        print(f"  Task ID:       {info['task_id']}")
        print(f"  Chat ID:       {info['chat_id']}")
        print(f"  Timestamp:     {format_timestamp(info['timestamp'])}")
        print(f"  Status:        {'❌ ERROR DETECTED' if info['has_error'] else '✅ OK'}")
        print(f"  Stages:        {', '.join(info['stages_completed']) if info['stages_completed'] else 'None'}")
        if info['model_used']:
            print(f"  Model:         {info['model_used']}")
        if info['tokens_used']:
            print(f"  Tokens:        {info['tokens_used']:,}")
        if info['message_count']:
            print(f"  Messages:      {info['message_count']}")
        print()
    
    print("=" * 80 + "\n")


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
            'note': 'This file contains FULL debug data for admin AI request processing. Only admin user requests are cached. Entries are sorted chronologically (oldest first). Data auto-expires after 72 hours in cache.',
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
    """Main function that inspects debug request entries with multiple viewing modes."""
    parser = argparse.ArgumentParser(
        description='Inspect the last 10 AI request debug entries with flexible viewing options',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick list of all requests
  %(prog)s --list
  
  # Detailed summary with statistics
  %(prog)s --summary
  
  # Filter by chat and show list
  %(prog)s --chat-id abc123 --list
  
  # Filter by task ID
  %(prog)s --task-id celery-task-123 --summary
  
  # Show only recent requests (last 5 minutes)
  %(prog)s --since-minutes 5 --list
  
  # Show only requests with errors
  %(prog)s --errors-only --list
  
  # Save full YAML output
  %(prog)s --yaml --output /tmp/debug.yml
  
  # Clear all cached debug data
  %(prog)s --clear
  
  # JSON output for scripts
  %(prog)s --json
        """
    )
    
    # Filtering options
    filter_group = parser.add_argument_group('Filtering Options')
    filter_group.add_argument(
        '--chat-id',
        type=str,
        default=None,
        help='Filter by chat ID'
    )
    filter_group.add_argument(
        '--task-id',
        type=str,
        default=None,
        help='Filter by task ID'
    )
    filter_group.add_argument(
        '--since-minutes',
        type=int,
        default=None,
        help='Only show entries from the last N minutes'
    )
    filter_group.add_argument(
        '--errors-only',
        action='store_true',
        help='Only show entries with detected errors'
    )
    
    # Output mode options
    output_group = parser.add_argument_group('Output Mode (choose one)')
    output_mode = output_group.add_mutually_exclusive_group()
    output_mode.add_argument(
        '--list',
        action='store_true',
        help='Show concise list view (default if no mode specified)'
    )
    output_mode.add_argument(
        '--summary',
        action='store_true',
        help='Show detailed summary with statistics'
    )
    output_mode.add_argument(
        '--yaml',
        action='store_true',
        help='Save full YAML output to file'
    )
    output_mode.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON (for programmatic use)'
    )
    
    # Other options
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=None,
        help='Output file path for YAML mode (default: debug_output/last_requests_<timestamp>.yml)'
    )
    parser.add_argument(
        '--clear',
        action='store_true',
        help='Clear all cached debug request data and exit'
    )
    
    args = parser.parse_args()
    
    # Initialize services
    cache_service = CacheService()
    encryption_service = EncryptionService(
        cache_service=cache_service
    )
    
    try:
        # Ensure cache client is connected
        await cache_service.client
        
        # Handle clear command
        if args.clear:
            script_logger.info("Clearing all debug request cache data...")
            success = await cache_service.clear_debug_requests()
            if success:
                print("\n✅ Successfully cleared all debug request cache data.\n")
            else:
                print("\n❌ Failed to clear debug request cache data.\n")
            return
        
        script_logger.info("Fetching debug request entries...")
        
        # Get debug entries (apply chat_id filter if specified)
        if args.chat_id:
            entries = await cache_service.get_debug_requests_for_chat(
                encryption_service=encryption_service,
                chat_id=args.chat_id
            )
        else:
            entries = await cache_service.get_all_debug_requests(
                encryption_service=encryption_service
            )
        
        # Apply additional filters
        filtered_entries = entries.copy()
        
        # Filter by task_id
        if args.task_id:
            filtered_entries = [e for e in filtered_entries if e.get('task_id') == args.task_id]
            script_logger.info(f"Filtered by task_id: {args.task_id} ({len(filtered_entries)} entries)")
        
        # Filter by time range
        if args.since_minutes:
            cutoff_time = int(time.time()) - (args.since_minutes * 60)
            filtered_entries = [e for e in filtered_entries if e.get('timestamp', 0) >= cutoff_time]
            script_logger.info(f"Filtered by time: last {args.since_minutes} minutes ({len(filtered_entries)} entries)")
        
        # Filter by errors
        if args.errors_only:
            filtered_entries = [e for e in filtered_entries if extract_key_info(e)['has_error']]
            script_logger.info(f"Filtered by errors: {len(filtered_entries)} entries with errors")
        
        # Check if we have any entries after filtering
        if not filtered_entries:
            print("\n❌ No debug request entries found matching the specified filters.")
            print("Note: Only admin user requests are cached (72-hour retention).")
            if not entries:
                print("Tip: Make sure an admin user has sent recent requests to the AI.\n")
            else:
                print(f"Total entries in cache: {len(entries)} (before filters)\n")
            return
        
        # Sort chronologically (oldest first)
        sorted_entries = sorted(filtered_entries, key=lambda e: e.get('timestamp', 0))
        
        # Determine output mode (default to list if nothing specified)
        if args.json:
            # JSON output mode
            output_data = {
                'metadata': {
                    'generated_at': datetime.now().isoformat(),
                    'total_entries': len(sorted_entries),
                    'filters_applied': {
                        'chat_id': args.chat_id,
                        'task_id': args.task_id,
                        'since_minutes': args.since_minutes,
                        'errors_only': args.errors_only,
                    }
                },
                'entries': sorted_entries
            }
            print(json_module.dumps(output_data, indent=2, default=str))
            
        elif args.yaml:
            # YAML output mode
            yaml_data = prepare_yaml_output(sorted_entries, args.chat_id)
            
            # Determine output path
            if args.output:
                output_path = args.output
            else:
                # Generate timestamped filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                chat_suffix = f"_chat_{args.chat_id[:8]}" if args.chat_id else ""
                task_suffix = f"_task_{args.task_id[:8]}" if args.task_id else ""
                filename = f"last_requests_{timestamp}{chat_suffix}{task_suffix}.yml"
                output_path = os.path.join(DEFAULT_OUTPUT_DIR, filename)
            
            # Save to YAML file
            saved_path = save_to_yaml(yaml_data, output_path)
            
            print("\n" + "=" * 80)
            print("DEBUG DATA SAVED SUCCESSFULLY")
            print("=" * 80)
            print(f"Output file:    {saved_path}")
            print(f"Total entries:  {len(sorted_entries)}")
            if args.chat_id:
                print(f"Chat ID filter: {args.chat_id}")
            if args.task_id:
                print(f"Task ID filter: {args.task_id}")
            if args.since_minutes:
                print(f"Time filter:    Last {args.since_minutes} minutes")
            if args.errors_only:
                print("Error filter:   Errors only")
            print("=" * 80)
            print("\nTo view the file:")
            print(f"  cat {saved_path}")
            print("\nTo copy to host machine:")
            print(f"  docker cp api:{saved_path} ./debug_output.yml\n")
            
        elif args.summary:
            # Summary view mode
            print_summary_view(sorted_entries)
            
        else:
            # List view mode (default)
            print_list_view(sorted_entries)
        
    except Exception as e:
        script_logger.error(f"Error during inspection: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
