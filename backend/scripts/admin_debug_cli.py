#!/usr/bin/env python3
"""
Admin Debug CLI Tool

A command-line interface for accessing the Admin Debug API endpoints on production
or development servers. Loads the admin API key from Vault.

This script is designed to be run via docker exec:
    docker exec api python /app/backend/scripts/admin_debug_cli.py <command> [options]

Commands:
    logs        - Query Docker Compose logs from Loki
    issues      - List issue reports
    issue       - Get details of a specific issue
    user        - Inspect a user by email
    chat        - Inspect a chat by ID
    embed       - Inspect an embed by ID
    requests    - Inspect recent AI requests

Examples:
    # Get logs from api service in last 30 minutes
    docker exec api python /app/backend/scripts/admin_debug_cli.py logs --services api --since 30

    # Get logs with error filtering
    docker exec api python /app/backend/scripts/admin_debug_cli.py logs --services api,task-worker --search "ERROR|WARNING"

    # List unprocessed issues
    docker exec api python /app/backend/scripts/admin_debug_cli.py issues

    # Inspect a user
    docker exec api python /app/backend/scripts/admin_debug_cli.py user someone@example.com

    # Inspect a chat
    docker exec api python /app/backend/scripts/admin_debug_cli.py chat <chat_id>

Vault Secret Path:
    The admin API key is stored in Vault at:
    kv/data/providers/admin with key "debug_cli__api_key"
    (following the SECRET__{PROVIDER}__{KEY} convention)
    
    To set this up, add to your environment:
    SECRET__ADMIN__DEBUG_CLI__API_KEY=sk-api-xxxxx
    Then restart vault-setup to import: docker compose ... restart vault-setup
"""

import argparse
import asyncio
import json
import sys
from typing import Optional

import httpx

# Add the backend to the path for imports
sys.path.insert(0, '/app')


def censor_email(email: str | None) -> str | None:
    """
    Censor an email address to protect user privacy.

    Shows only the first 2 characters of the local part and the full domain.
    Example: "john.doe@example.com" -> "jo***@example.com"
    """
    if not email or '@' not in email:
        return email
    local, domain = email.rsplit('@', 1)
    if len(local) <= 2:
        censored_local = local[0] + '***' if local else '***'
    else:
        censored_local = local[:2] + '***'
    return f"{censored_local}@{domain}"


# Keys known to contain email addresses in API responses
_EMAIL_KEYS = {'contact_email', 'email'}


def censor_emails_in_data(data: object) -> object:
    """
    Recursively walk a JSON-serializable structure and censor all email fields.

    Modifies dicts in-place and returns the same reference for convenience.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if key in _EMAIL_KEYS and isinstance(value, str):
                data[key] = censor_email(value)
            else:
                censor_emails_in_data(value)
    elif isinstance(data, list):
        for item in data:
            censor_emails_in_data(item)
    return data

# API base URLs - when running inside Docker, use internal service names
# For production debugging, we hit the external API
PROD_API_URL = "https://api.openmates.org/v1/admin/debug"
DEV_API_URL = "https://api.dev.openmates.org/v1/admin/debug"


async def get_api_key_from_vault() -> str:
    """Get the admin API key from Vault.
    
    The SECRET__ADMIN__DEBUG_CLI__API_KEY env var is imported by vault-setup
    into kv/data/providers/admin with key "debug_cli__api_key" (following the
    SECRET__{PROVIDER}__{KEY} convention).
    """
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    
    try:
        api_key = await secrets_manager.get_secret("kv/data/providers/admin", "debug_cli__api_key")
        if not api_key:
            print("Error: Admin API key not found in Vault at kv/data/providers/admin (key: debug_cli__api_key)", file=sys.stderr)
            print("", file=sys.stderr)
            print("To set up the admin API key:", file=sys.stderr)
            print("1. Generate an API key for an admin user in the OpenMates app", file=sys.stderr)
            print("2. Add to your environment: SECRET__ADMIN__DEBUG_CLI__API_KEY=sk-api-xxxxx", file=sys.stderr)
            print("3. Restart the vault-setup container to import the secret", file=sys.stderr)
            sys.exit(1)
        return api_key
    finally:
        await secrets_manager.aclose()


def get_base_url(use_dev: bool = False) -> str:
    """Get the API base URL."""
    return DEV_API_URL if use_dev else PROD_API_URL


async def make_request(
    endpoint: str,
    api_key: str,
    base_url: str,
    params: Optional[dict] = None,
    method: str = "GET"
) -> dict:
    """Make an authenticated request to the admin debug API."""
    url = f"{base_url}/{endpoint}"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            if method == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers, params=params)
            else:
                print(f"Error: Unsupported method {method}", file=sys.stderr)
                sys.exit(1)
            
            if response.status_code == 401:
                print("Error: Invalid or expired API key", file=sys.stderr)
                sys.exit(1)
            elif response.status_code == 403:
                print("Error: Admin privileges required", file=sys.stderr)
                sys.exit(1)
            elif response.status_code == 404:
                print("Error: Resource not found", file=sys.stderr)
                sys.exit(1)
            elif response.status_code != 200:
                print(f"Error: API returned status {response.status_code}", file=sys.stderr)
                try:
                    print(response.json(), file=sys.stderr)
                except Exception:
                    print(response.text, file=sys.stderr)
                sys.exit(1)
            
            return response.json()
    
    except httpx.ConnectError:
        print(f"Error: Could not connect to {base_url}", file=sys.stderr)
        sys.exit(1)
    except httpx.TimeoutException:
        print("Error: Request timed out", file=sys.stderr)
        sys.exit(1)


async def cmd_logs(args, api_key: str):
    """Query Docker Compose logs."""
    base_url = get_base_url(args.dev)
    
    params = {
        "lines": args.lines,
        "since_minutes": args.since,
    }
    if args.services:
        params["services"] = args.services
    if args.search:
        params["search"] = args.search
    
    result = await make_request("logs", api_key, base_url, params)
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"=== Logs from {result.get('services_queried', [])} ===")
        print(f"Time window: {result.get('time_window_minutes')} minutes")
        if result.get('search_pattern'):
            print(f"Search pattern: {result.get('search_pattern')}")
        print()
        print(result.get("logs", "No logs found"))


async def cmd_issues(args, api_key: str):
    """List issue reports."""
    base_url = get_base_url(args.dev)
    
    params = {
        "limit": args.limit,
        "offset": args.offset,
        "include_processed": args.include_processed,
    }
    if args.search:
        params["search"] = args.search
    
    result = await make_request("issues", api_key, base_url, params)
    
    if args.json:
        print(json.dumps(censor_emails_in_data(result), indent=2))
    else:
        issues = result.get("issues", [])
        print(f"=== Issue Reports ({len(issues)} found) ===\n")
        
        for issue in issues:
            print(f"ID: {issue.get('id')}")
            print(f"  Title: {issue.get('title')}")
            print(f"  Email: {censor_email(issue.get('contact_email')) or 'N/A'}")
            print(f"  URL: {issue.get('chat_or_embed_url') or 'N/A'}")
            print(f"  Created: {issue.get('created_at')}")
            print(f"  Processed: {issue.get('processed')}")
            if issue.get('description'):
                desc = issue['description'][:100] + "..." if len(issue['description']) > 100 else issue['description']
                print(f"  Description: {desc}")
            print()


async def cmd_issue(args, api_key: str):
    """Get details of a specific issue."""
    base_url = get_base_url(args.dev)
    
    params = {"include_logs": args.include_logs}
    
    result = await make_request(f"issues/{args.issue_id}", api_key, base_url, params)
    
    if args.json:
        print(json.dumps(censor_emails_in_data(result), indent=2))
    else:
        print(f"=== Issue: {result.get('title')} ===\n")
        print(f"ID: {result.get('id')}")
        print(f"Email: {censor_email(result.get('contact_email')) or 'N/A'}")
        print(f"URL: {result.get('chat_or_embed_url') or 'N/A'}")
        print(f"Location: {result.get('estimated_location') or 'N/A'}")
        print(f"Device: {result.get('device_info') or 'N/A'}")
        print(f"Created: {result.get('created_at')}")
        print(f"Processed: {result.get('processed')}")
        print(f"\nDescription:\n{result.get('description') or 'N/A'}")
        
        if result.get('full_report'):
            print("\n=== Full Report ===")
            print(json.dumps(result['full_report'], indent=2))


async def cmd_user(args, api_key: str):
    """Inspect a user by email."""
    base_url = get_base_url(args.dev)
    
    params = {
        "recent_limit": args.recent_limit,
        "include_cache": args.include_cache,
    }
    
    email = args.email
    result = await make_request(f"inspect/user/{email}", api_key, base_url, params)
    
    if args.json:
        print(json.dumps(censor_emails_in_data(result), indent=2))
    else:
        data = result.get("data", {})
        user = data.get("user_metadata", {})
        
        print(f"=== User: {censor_email(data.get('email'))} ===\n")
        print(f"ID: {user.get('id')}")
        print(f"Username: {user.get('username') or 'N/A'}")
        print(f"Is Admin: {user.get('is_server_admin')}")
        print(f"TFA Enabled: {user.get('tfa_enabled')}")
        print(f"Passkeys: {len(user.get('passkeys') or [])}")
        print(f"Lookup Hashes Count: {len(user.get('lookup_hashes') or [])}")
        
        # Show lookup hashes (important for debugging login issues)
        lookup_hashes = user.get('lookup_hashes') or []
        if lookup_hashes:
            print("Lookup Hashes:")
            for i, h in enumerate(lookup_hashes[:5]):
                display_hash = f"{h[:30]}..." if len(str(h)) > 30 else h
                print(f"  [{i}]: {display_hash}")
            if len(lookup_hashes) > 5:
                print(f"  ... and {len(lookup_hashes) - 5} more")
        
        print(f"Credits: {user.get('credits')}")
        print(f"Subscription: {user.get('subscription_status') or 'N/A'}")
        print(f"Language: {user.get('language')}")
        print(f"Created: {user.get('date_created')}")
        print(f"Last Access: {user.get('last_access')}")
        
        print("\n=== Item Counts ===")
        for k, v in data.get("item_counts", {}).items():
            print(f"  {k}: {v}")
        
        print("\n=== Cache Status ===")
        cache = data.get("cache", {})
        print(f"  Primed: {cache.get('primed')}")
        print(f"  Chat IDs Versions: {cache.get('chat_ids_versions_count')}")
        print(f"  Total Keys: {cache.get('total_keys_found')}")
        
        if data.get("recent_chats"):
            print("\n=== Recent Chats ===")
            for chat in data["recent_chats"]:
                print(f"  {chat.get('id')} - updated: {chat.get('updated_at')}")


async def cmd_chat(args, api_key: str):
    """Inspect a chat by ID."""
    base_url = get_base_url(args.dev)
    
    params = {
        "messages_limit": args.messages_limit,
        "embeds_limit": args.embeds_limit,
        "usage_limit": args.usage_limit,
        "include_cache": args.include_cache,
    }
    
    result = await make_request(f"inspect/chat/{args.chat_id}", api_key, base_url, params)
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        data = result.get("data", {})
        meta = data.get("chat_metadata") or {}
        
        print(f"=== Chat: {data.get('chat_id')} ===\n")
        print(f"Created: {meta.get('created_at')}")
        print(f"Updated: {meta.get('updated_at')}")
        print(f"Messages: {data.get('messages', {}).get('count', 0)}")
        print(f"Embeds: {data.get('embeds', {}).get('count', 0)}")
        print(f"Usage entries: {data.get('usage', {}).get('count', 0)}")
        
        cache = data.get("cache", {})
        if cache:
            print("\n=== Cache Status ===")
            print(f"  Discovered User ID: {cache.get('discovered_user_id')}")
            print(f"  Keys Found: {cache.get('total_keys_found')}")
            if cache.get('chat_versions'):
                print(f"  Versions: {cache.get('chat_versions')}")


async def cmd_embed(args, api_key: str):
    """Inspect an embed by ID."""
    base_url = get_base_url(args.dev)
    
    result = await make_request(f"inspect/embed/{args.embed_id}", api_key, base_url)
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        data = result.get("data", {})
        embed = data.get("embed_metadata") or {}
        
        print(f"=== Embed: {data.get('embed_id')} ===\n")
        print(f"Type: {embed.get('embed_type')}")
        print(f"Created: {embed.get('created_at')}")
        print(f"Expires: {embed.get('expires_at') or 'Never'}")
        print(f"Keys: {len(data.get('embed_keys', []))}")
        print(f"Child Embeds: {len(data.get('child_embeds', []))}")


async def cmd_requests(args, api_key: str):
    """Inspect recent AI requests."""
    base_url = get_base_url(args.dev)
    
    params = {}
    if args.chat_id:
        params["chat_id"] = args.chat_id
    
    result = await make_request("inspect/last-requests", api_key, base_url, params)
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        data = result.get("data", {})
        requests_data = data.get("requests", [])
        
        print(f"=== Recent AI Requests ({len(requests_data)} found) ===\n")
        
        for req in requests_data[:10]:  # Show first 10
            print(f"Timestamp: {req.get('timestamp')}")
            print(f"  Chat ID: {req.get('chat_id')}")
            print(f"  Model: {req.get('model')}")
            print(f"  Provider: {req.get('provider')}")
            print(f"  Tokens: {req.get('total_tokens')}")
            print()


async def cmd_newsletter(args, api_key: str):
    """Inspect newsletter subscription data."""
    base_url = get_base_url(args.dev)

    params = {}
    if args.show_emails:
        params["show_emails"] = "true"
    if args.show_pending:
        params["show_pending"] = "true"
    if args.timeline:
        params["timeline"] = "true"

    result = await make_request("newsletter", api_key, base_url, params)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    summary = result.get("summary", {})

    print()
    print("=" * 60)
    print("  NEWSLETTER SUBSCRIBERS REPORT")
    print("=" * 60)
    print()
    print("  SUMMARY")
    print("  " + "-" * 40)
    print(f"  Confirmed subscribers:    {summary.get('confirmed_subscribers', 0)}")
    print(f"  Unconfirmed records:      {summary.get('unconfirmed_records', 0)}")
    print(f"  Total Directus records:   {summary.get('total_records_in_directus', 0)}")
    print(f"  Blocked/ignored emails:   {summary.get('ignored_blocked_emails', 0)}")
    print(f"  Darkmode preference:      {summary.get('darkmode_subscribers', 0)}")
    print()

    lang_breakdown = summary.get("language_breakdown", {})
    if lang_breakdown:
        print("  LANGUAGE BREAKDOWN")
        print("  " + "-" * 40)
        for lang, count in lang_breakdown.items():
            print(f"    {lang:10s}  {count}")
        print()

    if args.show_pending:
        pending = result.get("pending_in_cache", {})
        pending_count = pending.get("count", 0)
        print("  PENDING (UNCONFIRMED) IN CACHE")
        print("  " + "-" * 40)
        print(f"  Count: {pending_count}")
        if pending_count > 0:
            print()
            for entry in pending.get("entries", []):
                email = entry.get("email", "unknown")
                expires = entry.get("expires_in_minutes", "?")
                created = entry.get("created_at", "unknown")
                print(f"    {email:30s}  lang={entry.get('language', '?'):5s}  expires in {expires} min  (requested: {created})")
        else:
            print("  No pending subscriptions in cache.")
            print("  (Pending entries expire after 30 minutes)")
        print()

    if args.show_emails:
        subscribers = result.get("subscribers", [])
        print("  SUBSCRIBERS (DECRYPTED)")
        print("  " + "-" * 40)
        if subscribers:
            for i, sub in enumerate(subscribers, 1):
                email = sub.get("email", "[unknown]")
                confirmed = sub.get("confirmed_at", "N/A")
                subscribed = sub.get("subscribed_at", "N/A")
                lang = sub.get("language", "?")
                dark = "dark" if sub.get("darkmode") else "light"
                has_unsub = "yes" if sub.get("has_unsubscribe_token") else "NO"
                print(f"    {i}. {email}")
                print(f"       Confirmed:    {confirmed}")
                print(f"       Subscribed:   {subscribed}")
                print(f"       Language:     {lang}")
                print(f"       Theme:        {dark}")
                print(f"       Unsub token:  {has_unsub}")
                print()
        else:
            print("  No subscribers found.")
        print()

    if args.timeline:
        timeline = result.get("timeline_monthly", {})
        print("  SUBSCRIPTION TIMELINE (MONTHLY)")
        print("  " + "-" * 40)
        if timeline:
            for month, count in timeline.items():
                bar = "#" * min(count, 80)
                print(f"    {month}  {count:3d}  {bar}")
        else:
            print("  No subscription data available.")
        print()

    print("=" * 60)
    print()


async def async_main(args):
    """Async main function."""
    # Get API key from Vault
    api_key = await get_api_key_from_vault()
    
    # Show which server we're using
    server = "DEVELOPMENT" if args.dev else "PRODUCTION"
    print(f"[Using {server} server]\n", file=sys.stderr)
    
    # Call the appropriate command
    await args.func(args, api_key)


def main():
    parser = argparse.ArgumentParser(
        description="Admin Debug CLI for OpenMates (run via docker exec)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--dev", action="store_true", help="Use development server instead of production")
    parser.add_argument("--json", action="store_true", help="Output raw JSON response")
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # logs command
    logs_parser = subparsers.add_parser("logs", help="Query Docker Compose logs")
    logs_parser.add_argument("--services", "-s", help="Comma-separated list of services (default: all)")
    logs_parser.add_argument("--lines", "-n", type=int, default=100, help="Lines per service (default: 100, max: 500)")
    logs_parser.add_argument("--since", "-t", type=int, default=60, help="Minutes to look back (default: 60, max: 1440)")
    logs_parser.add_argument("--search", "-g", help="Regex pattern to filter logs")
    logs_parser.set_defaults(func=cmd_logs)
    
    # issues command
    issues_parser = subparsers.add_parser("issues", help="List issue reports")
    issues_parser.add_argument("--search", "-s", help="Search in title/description")
    issues_parser.add_argument("--limit", "-n", type=int, default=50, help="Max results (default: 50)")
    issues_parser.add_argument("--offset", "-o", type=int, default=0, help="Pagination offset")
    issues_parser.add_argument("--include-processed", "-p", action="store_true", help="Include processed issues")
    issues_parser.set_defaults(func=cmd_issues)
    
    # issue command
    issue_parser = subparsers.add_parser("issue", help="Get issue details")
    issue_parser.add_argument("issue_id", help="Issue ID")
    issue_parser.add_argument("--include-logs", "-l", action="store_true", help="Include related logs")
    issue_parser.set_defaults(func=cmd_issue)
    
    # user command
    user_parser = subparsers.add_parser("user", help="Inspect a user by email")
    user_parser.add_argument("email", help="User's email address")
    user_parser.add_argument("--recent-limit", "-n", type=int, default=5, help="Recent items limit (default: 5)")
    user_parser.add_argument("--no-cache", dest="include_cache", action="store_false", help="Skip cache inspection")
    user_parser.set_defaults(func=cmd_user)
    
    # chat command
    chat_parser = subparsers.add_parser("chat", help="Inspect a chat by ID")
    chat_parser.add_argument("chat_id", help="Chat ID")
    chat_parser.add_argument("--messages-limit", "-m", type=int, default=50, help="Messages limit (default: 50)")
    chat_parser.add_argument("--embeds-limit", "-e", type=int, default=10, help="Embeds limit (default: 10)")
    chat_parser.add_argument("--usage-limit", "-u", type=int, default=20, help="Usage entries limit (default: 20)")
    chat_parser.add_argument("--no-cache", dest="include_cache", action="store_false", help="Skip cache inspection")
    chat_parser.set_defaults(func=cmd_chat)
    
    # embed command
    embed_parser = subparsers.add_parser("embed", help="Inspect an embed by ID")
    embed_parser.add_argument("embed_id", help="Embed ID")
    embed_parser.set_defaults(func=cmd_embed)
    
    # requests command
    requests_parser = subparsers.add_parser("requests", help="Inspect recent AI requests")
    requests_parser.add_argument("--chat-id", "-c", help="Filter by chat ID")
    requests_parser.set_defaults(func=cmd_requests)
    
    # newsletter command
    newsletter_parser = subparsers.add_parser("newsletter", help="Inspect newsletter subscription data")
    newsletter_parser.add_argument("--show-emails", "-e", action="store_true", help="Decrypt and show subscriber emails")
    newsletter_parser.add_argument("--show-pending", "-p", action="store_true", help="Show pending subscriptions from cache")
    newsletter_parser.add_argument("--timeline", "-t", action="store_true", help="Show monthly subscription timeline")
    newsletter_parser.set_defaults(func=cmd_newsletter)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
