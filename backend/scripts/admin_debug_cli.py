#!/usr/bin/env python3
"""
Admin Debug CLI Tool

A command-line interface for accessing the Admin Debug API endpoints on production
or development servers. Loads the admin API key from Vault.

This script is designed to be run via docker exec:
    docker exec api python /app/backend/scripts/admin_debug_cli.py <command> [options]

Commands:
    logs          - Query Docker Compose logs from Loki (core API server)
    upload-logs   - Query Docker logs from the upload server (upload.openmates.org)
    preview-logs  - Query Docker logs from the preview server (preview.openmates.org)
    upload-update - git pull + rebuild + restart upload server containers
    preview-update - git pull + rebuild + restart preview server containers
    issues        - List issue reports
    issue         - Get details of a specific issue
    issue-delete  - Delete an issue (after confirmed fixed)
    user          - Inspect a user by email
    chat          - Inspect a chat by ID
    embed         - Inspect an embed by ID
    requests      - Inspect recent AI requests
    newsletter    - Inspect newsletter subscription data

Examples:
    # Get logs from api service in last 30 minutes
    docker exec api python /app/backend/scripts/admin_debug_cli.py logs --services api --since 30

    # Get logs with error filtering
    docker exec api python /app/backend/scripts/admin_debug_cli.py logs --services api,task-worker --search "ERROR|WARNING"

    # Get upload server logs (last 60 min, app-uploads service)
    docker exec api python /app/backend/scripts/admin_debug_cli.py upload-logs

    # Get upload server logs with filtering
    docker exec api python /app/backend/scripts/admin_debug_cli.py upload-logs --services app-uploads,clamav --since 30 --search "ERROR"

    # Get preview server logs
    docker exec api python /app/backend/scripts/admin_debug_cli.py preview-logs --since 30 --lines 200

    # List unprocessed issues
    docker exec api python /app/backend/scripts/admin_debug_cli.py issues

    # Trigger a full self-update of the upload server (git pull + rebuild + restart)
    docker exec api python /app/backend/scripts/admin_debug_cli.py upload-update

    # Trigger a full self-update of the preview server
    docker exec api python /app/backend/scripts/admin_debug_cli.py preview-update

    # Inspect a user
    docker exec api python /app/backend/scripts/admin_debug_cli.py user someone@example.com

    # Inspect a chat
    docker exec api python /app/backend/scripts/admin_debug_cli.py chat <chat_id>

Vault Secret Paths:
    Core API admin key:
        kv/data/providers/admin  key: "debug_cli__api_key"
        Set via: SECRET__ADMIN__DEBUG_CLI__API_KEY=sk-api-xxxxx

    Upload server admin log key:
        kv/data/providers/upload_server  key: "admin_log_api_key"
        Set via: SECRET__UPLOAD_SERVER__ADMIN_LOG_API_KEY=<random-key>
        Also add ADMIN_LOG_API_KEY=<same-key> to the upload VM's .env

    Preview server admin log key:
        kv/data/providers/preview_server  key: "admin_log_api_key"
        Set via: SECRET__PREVIEW_SERVER__ADMIN_LOG_API_KEY=<random-key>
        Also add ADMIN_LOG_API_KEY=<same-key> to the preview VM's .env

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

# Upload and preview servers run on separate VMs — always hit their public URLs.
# (There is no dev-specific upload or preview server.)
# Caddy on each VM routes /admin/* to the admin-sidecar container (port 8001),
# which holds the Docker socket. The main service containers do NOT have Docker access.
UPLOAD_SERVER_URL = "https://upload.openmates.org/admin/logs"
PREVIEW_SERVER_URL = "https://preview.openmates.org/admin/logs"

# Update endpoints — trigger git pull + rebuild + restart on the satellite VM.
# Served by the admin-sidecar container. Never available on the core API server.
UPLOAD_SERVER_UPDATE_URL = "https://upload.openmates.org/admin/update"
PREVIEW_SERVER_UPDATE_URL = "https://preview.openmates.org/admin/update"


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


async def get_satellite_log_key(vault_path: str, vault_key: str, server_name: str) -> str:
    """
    Fetch a satellite server's admin log API key from the core Vault.

    The key is stored under SECRET__{PROVIDER}__{KEY} convention and imported
    into Vault by vault-setup. For example:
        SECRET__UPLOAD_SERVER__ADMIN_LOG_API_KEY → kv/data/providers/upload_server
        key: "admin_log_api_key"

    Args:
        vault_path:  Vault KV path (e.g. "kv/data/providers/upload_server")
        vault_key:   Key within that path (e.g. "admin_log_api_key")
        server_name: Human-readable name for error messages (e.g. "upload server")

    Returns:
        The API key string.
    """
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()

    try:
        api_key = await secrets_manager.get_secret(vault_path, vault_key)
        if not api_key:
            print(
                f"Error: Admin log key for {server_name} not found in Vault at "
                f"{vault_path} (key: {vault_key})",
                file=sys.stderr,
            )
            print("", file=sys.stderr)
            print(f"To set up the {server_name} admin log key:", file=sys.stderr)
            print(
                "1. Generate a random secret: python3 -c \"import secrets; print(secrets.token_hex(32))\"",
                file=sys.stderr,
            )
            if "upload" in server_name:
                print(
                    "2. Add to core server .env: SECRET__UPLOAD_SERVER__ADMIN_LOG_API_KEY=<key>",
                    file=sys.stderr,
                )
                print("3. Add to upload VM's .env: ADMIN_LOG_API_KEY=<same-key>", file=sys.stderr)
            else:
                print(
                    "2. Add to core server .env: SECRET__PREVIEW_SERVER__ADMIN_LOG_API_KEY=<key>",
                    file=sys.stderr,
                )
                print("3. Add to preview VM's .env: ADMIN_LOG_API_KEY=<same-key>", file=sys.stderr)
            print("4. Restart vault-setup: docker compose ... restart vault-setup", file=sys.stderr)
            sys.exit(1)
        return api_key
    finally:
        await secrets_manager.aclose()


async def _fetch_satellite_logs(
    url: str,
    api_key: str,
    services: Optional[str],
    lines: int,
    since: int,
    search: Optional[str],
) -> str:
    """
    Call the /admin/logs endpoint on a satellite server (upload or preview).

    Args:
        url:      Full URL of the admin logs endpoint.
        api_key:  X-Admin-Log-Key secret.
        services: Comma-separated service names (or None for default).
        lines:    Number of log lines to return.
        since:    Time window in minutes.
        search:   Optional regex filter.

    Returns:
        Log output as plain text.
    """
    params: dict = {
        "lines": lines,
        "since_minutes": since,
    }
    if services:
        params["services"] = services
    if search:
        params["search"] = search

    headers = {"X-Admin-Log-Key": api_key}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, headers=headers, params=params)

        if response.status_code == 401:
            print("Error: Invalid admin log API key", file=sys.stderr)
            sys.exit(1)
        elif response.status_code == 503:
            print(
                "Error: Admin logs endpoint not configured on the server "
                "(ADMIN_LOG_API_KEY env var not set on the satellite VM)",
                file=sys.stderr,
            )
            sys.exit(1)
        elif response.status_code == 400:
            print(f"Error: {response.text}", file=sys.stderr)
            sys.exit(1)
        elif response.status_code != 200:
            print(f"Error: Server returned {response.status_code}", file=sys.stderr)
            print(response.text, file=sys.stderr)
            sys.exit(1)

        return response.text

    except httpx.ConnectError:
        print(f"Error: Could not connect to {url}", file=sys.stderr)
        sys.exit(1)
    except httpx.TimeoutException:
        print("Error: Request timed out (log fetch took > 60s)", file=sys.stderr)
        sys.exit(1)


async def cmd_upload_logs(args, _unused_api_key: str):
    """
    Fetch logs from the upload server (upload.openmates.org).

    Calls GET https://upload.openmates.org/admin/logs using the admin log API key
    stored in core Vault at kv/data/providers/upload_server (key: admin_log_api_key).

    The request is served by the admin-sidecar container on the upload VM (port 8001,
    proxied by Caddy). The sidecar runs docker compose logs and returns the output.
    The main app-uploads container does NOT have Docker socket access.
    Requires ADMIN_LOG_API_KEY to be set on the upload VM's admin-sidecar and the
    same value stored in the core Vault via SECRET__UPLOAD_SERVER__ADMIN_LOG_API_KEY.
    """
    api_key = await get_satellite_log_key(
        vault_path="kv/data/providers/upload_server",
        vault_key="admin_log_api_key",
        server_name="upload server",
    )

    output = await _fetch_satellite_logs(
        url=UPLOAD_SERVER_URL,
        api_key=api_key,
        services=args.services,
        lines=args.lines,
        since=args.since,
        search=args.search,
    )

    if args.json:
        print(json.dumps({"logs": output, "server": "upload"}))
    else:
        services_label = args.services or "app-uploads"
        print(f"=== Upload Server Logs [{services_label}] — last {args.since} min ===")
        if args.search:
            print(f"Search pattern: {args.search}")
        print()
        print(output)


async def cmd_preview_logs(args, _unused_api_key: str):
    """
    Fetch logs from the preview server (preview.openmates.org).

    Calls GET https://preview.openmates.org/admin/logs using the admin log API key
    stored in core Vault at kv/data/providers/preview_server (key: admin_log_api_key).

    The request is served by the admin-sidecar container on the preview VM (port 8001,
    proxied by Caddy). The sidecar runs docker compose logs and returns the output.
    Requires ADMIN_LOG_API_KEY to be set on the preview VM's admin-sidecar and the
    same value stored in the core Vault via SECRET__PREVIEW_SERVER__ADMIN_LOG_API_KEY.
    """
    api_key = await get_satellite_log_key(
        vault_path="kv/data/providers/preview_server",
        vault_key="admin_log_api_key",
        server_name="preview server",
    )

    output = await _fetch_satellite_logs(
        url=PREVIEW_SERVER_URL,
        api_key=api_key,
        services=args.services,
        lines=args.lines,
        since=args.since,
        search=args.search,
    )

    if args.json:
        print(json.dumps({"logs": output, "server": "preview"}))
    else:
        print(f"=== Preview Server Logs — last {args.since} min ===")
        if args.search:
            print(f"Search pattern: {args.search}")
        print()
        print(output)


async def _trigger_satellite_update(url: str, api_key: str, server_name: str) -> None:
    """
    Call the POST /admin/update endpoint on a satellite server (upload or preview).

    The endpoint is fire-and-forget: it returns 202 immediately and runs the
    update (git pull + docker compose build + up -d) in the background.
    Use the corresponding *-logs command to monitor progress afterward.

    Args:
        url:         Full URL of the /admin/update endpoint.
        api_key:     X-Admin-Log-Key secret.
        server_name: Human-readable name for error messages (e.g. "upload server").
    """
    headers = {"X-Admin-Log-Key": api_key}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers)

        if response.status_code == 401:
            print("Error: Invalid admin log API key", file=sys.stderr)
            sys.exit(1)
        elif response.status_code == 409:
            print("Error: An update is already in progress on the server.", file=sys.stderr)
            print("Use the *-logs command to monitor it.", file=sys.stderr)
            sys.exit(1)
        elif response.status_code == 503:
            print(
                "Error: Admin update endpoint not configured on the server "
                "(ADMIN_LOG_API_KEY or SERVICE_UPDATE_TARGET not set on the satellite VM)",
                file=sys.stderr,
            )
            sys.exit(1)
        elif response.status_code != 202:
            print(f"Error: Server returned {response.status_code}", file=sys.stderr)
            print(response.text, file=sys.stderr)
            sys.exit(1)

        # 202 Accepted — update started in background
        try:
            data = response.json()
            print(data.get("message", "Update accepted."))
        except Exception:
            print("Update accepted (202).")

    except httpx.ConnectError:
        print(f"Error: Could not connect to {url}", file=sys.stderr)
        sys.exit(1)
    except httpx.TimeoutException:
        print("Error: Request timed out", file=sys.stderr)
        sys.exit(1)


async def cmd_upload_update(args, _unused_api_key: str):
    """
    Trigger a full self-update of the upload server (upload.openmates.org).

    Calls POST https://upload.openmates.org/admin/update using the admin log API key
    stored in core Vault at kv/data/providers/upload_server (key: admin_log_api_key).

    The server runs:
      1. git pull
      2. docker compose build app-uploads
      3. docker compose up -d app-uploads

    Progress is streamed line by line so the operator sees live output.
    """
    api_key = await get_satellite_log_key(
        vault_path="kv/data/providers/upload_server",
        vault_key="admin_log_api_key",
        server_name="upload server",
    )

    print("=== Triggering update on upload server ===\n")
    await _trigger_satellite_update(
        url=UPLOAD_SERVER_UPDATE_URL,
        api_key=api_key,
        server_name="upload server",
    )


async def cmd_preview_update(args, _unused_api_key: str):
    """
    Trigger a full self-update of the preview server (preview.openmates.org).

    Calls POST https://preview.openmates.org/admin/update using the admin log API key
    stored in core Vault at kv/data/providers/preview_server (key: admin_log_api_key).

    The server runs:
      1. git pull
      2. docker compose build preview
      3. docker compose up -d preview

    Progress is streamed line by line so the operator sees live output.
    """
    api_key = await get_satellite_log_key(
        vault_path="kv/data/providers/preview_server",
        vault_key="admin_log_api_key",
        server_name="preview server",
    )

    print("=== Triggering update on preview server ===\n")
    await _trigger_satellite_update(
        url=PREVIEW_SERVER_UPDATE_URL,
        api_key=api_key,
        server_name="preview server",
    )


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


async def cmd_issue_delete(args, api_key: str):
    """Delete an issue (Directus + S3). Use after the issue is confirmed fixed."""
    base_url = get_base_url(args.dev)
    result = await make_request(f"issues/{args.issue_id}", api_key, base_url, method="DELETE")
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Success: {result.get('success')}")
        print(f"Message: {result.get('message')}")
        print(f"Deleted from S3: {result.get('deleted_from_s3')}")


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
    # Satellite commands fetch their own Vault keys internally — they don't need
    # the core API admin key and don't distinguish between dev and prod.
    _satellite_commands = {"upload-logs", "preview-logs", "upload-update", "preview-update"}
    if args.command in _satellite_commands:
        # Satellite commands are not server-specific (there is only one upload/preview VM).
        # Pass None as api_key — the commands fetch their own keys from Vault.
        await args.func(args, None)
        return

    # Get core API key from Vault (used by all other commands)
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
    
    # logs command (core API server via Loki)
    logs_parser = subparsers.add_parser("logs", help="Query Docker Compose logs from core API server (via Loki)")
    logs_parser.add_argument("--services", "-s", help="Comma-separated list of services (default: all)")
    logs_parser.add_argument("--lines", "-n", type=int, default=100, help="Lines per service (default: 100, max: 500)")
    logs_parser.add_argument("--since", "-t", type=int, default=60, help="Minutes to look back (default: 60, max: 1440)")
    logs_parser.add_argument("--search", "-g", help="Regex pattern to filter logs")
    logs_parser.set_defaults(func=cmd_logs)

    # upload-logs command (upload.openmates.org — separate VM, no Loki)
    upload_logs_parser = subparsers.add_parser(
        "upload-logs",
        help="Query Docker logs from the upload server (upload.openmates.org)",
    )
    upload_logs_parser.add_argument(
        "--services", "-s",
        default=None,
        help="Comma-separated services (default: app-uploads). Allowed: app-uploads, clamav, vault",
    )
    upload_logs_parser.add_argument(
        "--lines", "-n",
        type=int,
        default=100,
        help="Lines per service (default: 100, max: 500)",
    )
    upload_logs_parser.add_argument(
        "--since", "-t",
        type=int,
        default=60,
        help="Minutes to look back (default: 60, max: 1440)",
    )
    upload_logs_parser.add_argument(
        "--search", "-g",
        default=None,
        help="Regex pattern to filter log lines (case-insensitive)",
    )
    upload_logs_parser.set_defaults(func=cmd_upload_logs)

    # preview-logs command (preview.openmates.org — separate VM, no Loki)
    preview_logs_parser = subparsers.add_parser(
        "preview-logs",
        help="Query Docker logs from the preview server (preview.openmates.org)",
    )
    preview_logs_parser.add_argument(
        "--services", "-s",
        default=None,
        help="Services to fetch (default: preview). Currently only: preview",
    )
    preview_logs_parser.add_argument(
        "--lines", "-n",
        type=int,
        default=100,
        help="Number of log lines (default: 100, max: 500)",
    )
    preview_logs_parser.add_argument(
        "--since", "-t",
        type=int,
        default=60,
        help="Minutes to look back (default: 60, max: 1440)",
    )
    preview_logs_parser.add_argument(
        "--search", "-g",
        default=None,
        help="Regex pattern to filter log lines (case-insensitive)",
    )
    preview_logs_parser.set_defaults(func=cmd_preview_logs)

    # upload-update command (upload.openmates.org — git pull + rebuild + restart)
    upload_update_parser = subparsers.add_parser(  # noqa: F841
        "upload-update",
        help="git pull + rebuild + restart the upload server (upload.openmates.org)",
    )
    upload_update_parser.set_defaults(func=cmd_upload_update)

    # preview-update command (preview.openmates.org — git pull + rebuild + restart)
    preview_update_parser = subparsers.add_parser(  # noqa: F841
        "preview-update",
        help="git pull + rebuild + restart the preview server (preview.openmates.org)",
    )
    preview_update_parser.set_defaults(func=cmd_preview_update)

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

    # issue-delete command
    issue_delete_parser = subparsers.add_parser("issue-delete", help="Delete an issue (after confirmed fixed)")
    issue_delete_parser.add_argument("issue_id", help="Issue ID to delete")
    issue_delete_parser.add_argument("--json", "-j", action="store_true", help="Output raw JSON")
    issue_delete_parser.set_defaults(func=cmd_issue_delete)
    
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
