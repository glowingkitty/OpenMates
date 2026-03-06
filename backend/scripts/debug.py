#!/usr/bin/env python3
"""
Unified debug entry point for OpenMates backend.
Replaces all individual inspect_*.py scripts with a single command interface.

Architecture context: See docs/claude/debugging.md

Tests: None (inspection script, not production code)

USAGE
─────

Quick system health check (default — no subcommand):
    docker exec api python /app/backend/scripts/debug.py

Full health with details:
    docker exec api python /app/backend/scripts/debug.py health -v

Inspect a chat (health summary by default, -v for full details):
    docker exec api python /app/backend/scripts/debug.py chat <chat_id>
    docker exec api python /app/backend/scripts/debug.py chat <chat_id> -v
    docker exec api python /app/backend/scripts/debug.py chat <chat_id> -v --decrypt
    docker exec api python /app/backend/scripts/debug.py chat <chat_id> --prod

Inspect an embed:
    docker exec api python /app/backend/scripts/debug.py embed <embed_id>
    docker exec api python /app/backend/scripts/debug.py embed <embed_id> -v --decrypt
    docker exec api python /app/backend/scripts/debug.py embed <embed_id> --prod

Inspect a user:
    docker exec api python /app/backend/scripts/debug.py user <email>
    docker exec api python /app/backend/scripts/debug.py user <email> -v

User activity log timeline:
    docker exec api python /app/backend/scripts/debug.py logs <email>
    docker exec api python /app/backend/scripts/debug.py logs <email> --since 120
    docker exec api python /app/backend/scripts/debug.py logs <email> --level warning
    docker exec api python /app/backend/scripts/debug.py logs <email> --prod
    docker exec api python /app/backend/scripts/debug.py logs <email> --follow

Recent AI requests (admin only):
    docker exec api python /app/backend/scripts/debug.py requests
    docker exec api python /app/backend/scripts/debug.py requests -v
    docker exec api python /app/backend/scripts/debug.py requests --errors-only
    docker exec api python /app/backend/scripts/debug.py requests --show-prompt 3
    docker exec api python /app/backend/scripts/debug.py requests --diff 1 3

Issue reports:
    docker exec api python /app/backend/scripts/debug.py issue --list
    docker exec api python /app/backend/scripts/debug.py issue <issue_id>
    docker exec api python /app/backend/scripts/debug.py issue <issue_id> -v
    docker exec api python /app/backend/scripts/debug.py issue <issue_id> --delete

Replay a request by request_id (full Loki trace):
    docker exec api python /app/backend/scripts/debug.py replay <request_id>

Errors (top error fingerprints from Redis, with Loki sample):
    docker exec api python /app/backend/scripts/debug.py errors
    docker exec api python /app/backend/scripts/debug.py errors --top 20

Remote access via Admin Debug API:
    Add --prod to any command (where supported) to query production server.
    Add --dev to query dev server instead of prod.
"""

import sys
import argparse

# Add backend to path
sys.path.insert(0, '/app/backend')
sys.path.insert(0, '/app')


def _run_health(args):
    """Run system health check."""
    import asyncio
    from debug_health import run_health_check
    asyncio.run(run_health_check(verbose=getattr(args, 'verbose', False)))


def _run_chat(args):
    """Delegate to inspect_chat.py — either health summary or full inspection."""
    import asyncio
    import importlib.util
    import os
    verbose = getattr(args, 'verbose', False)

    if verbose or getattr(args, 'decrypt', False) or getattr(args, 'share_url', None) or getattr(args, 'share_key', None):
        # Full inspection mode — pass through to inspect_chat
        spec = importlib.util.spec_from_file_location(
            "inspect_chat",
            os.path.join(os.path.dirname(__file__), 'inspect_chat.py')
        )
        mod = importlib.util.load_from_spec(spec)
        spec.loader.exec_module(mod)
        # Build argv and call its main
        _argv = ['inspect_chat.py', args.chat_id]
        if getattr(args, 'decrypt', False):
            _argv.append('--decrypt')
        if getattr(args, 'no_cache', False):
            _argv.append('--no-cache')
        if getattr(args, 'share_url', None):
            _argv += ['--share-url', args.share_url]
        if getattr(args, 'share_key', None):
            _argv += ['--share-key', args.share_key]
        if getattr(args, 'share_password', None):
            _argv += ['--share-password', args.share_password]
        if getattr(args, 'prod', False):
            _argv.append('--production')
        if getattr(args, 'dev', False):
            _argv.append('--dev')
        if getattr(args, 'json', False):
            _argv.append('--json')
        sys.argv = _argv
        asyncio.run(mod.main())
    else:
        # Health summary mode
        asyncio.run(_chat_health_summary(args))


async def _chat_health_summary(args):
    """Show a brief health summary for a chat."""
    from debug_health import check_chat_health
    await check_chat_health(
        chat_id=args.chat_id,
        production=getattr(args, 'prod', False),
        dev=getattr(args, 'dev', False),
    )


def _run_embed(args):
    """Delegate to inspect_embed.py — either health summary or full inspection."""
    import asyncio
    import importlib.util
    import os
    verbose = getattr(args, 'verbose', False)

    if verbose or getattr(args, 'decrypt', False) or getattr(args, 'share_url', None):
        spec = importlib.util.spec_from_file_location(
            "inspect_embed",
            os.path.join(os.path.dirname(__file__), 'inspect_embed.py')
        )
        mod = importlib.util.load_from_spec(spec)
        spec.loader.exec_module(mod)
        _argv = ['inspect_embed.py', args.embed_id]
        if getattr(args, 'decrypt', False):
            _argv.append('--decrypt')
        if getattr(args, 'check_links', False):
            _argv.append('--check-links')
        if getattr(args, 'share_url', None):
            _argv += ['--share-url', args.share_url]
        if getattr(args, 'share_key', None):
            _argv += ['--share-key', args.share_key]
        if getattr(args, 'prod', False):
            _argv.append('--production')
        if getattr(args, 'dev', False):
            _argv.append('--dev')
        if getattr(args, 'json', False):
            _argv.append('--json')
        sys.argv = _argv
        asyncio.run(mod.main())
    else:
        asyncio.run(_embed_health_summary(args))


async def _embed_health_summary(args):
    """Show a brief health summary for an embed."""
    from debug_health import check_embed_health
    await check_embed_health(
        embed_id=args.embed_id,
        production=getattr(args, 'prod', False),
        dev=getattr(args, 'dev', False),
    )


def _run_user(args):
    """Delegate to inspect_user.py — either health summary or full inspection."""
    import asyncio
    import importlib.util
    import os
    verbose = getattr(args, 'verbose', False)

    if verbose:
        spec = importlib.util.spec_from_file_location(
            "inspect_user",
            os.path.join(os.path.dirname(__file__), 'inspect_user.py')
        )
        mod = importlib.util.load_from_spec(spec)
        spec.loader.exec_module(mod)
        _argv = ['inspect_user.py', args.email]
        if getattr(args, 'no_cache', False):
            _argv.append('--no-cache')
        if getattr(args, 'recent_limit', 5) != 5:
            _argv += ['--recent-limit', str(args.recent_limit)]
        if getattr(args, 'json', False):
            _argv.append('--json')
        sys.argv = _argv
        asyncio.run(mod.main())
    else:
        asyncio.run(_user_health_summary(args))


async def _user_health_summary(args):
    """Show a brief health summary for a user."""
    from debug_health import check_user_health
    await check_user_health(email=args.email)


def _run_logs(args):
    """Delegate to inspect_user_logs.py."""
    import asyncio
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location(
        "inspect_user_logs",
        os.path.join(os.path.dirname(__file__), 'inspect_user_logs.py')
    )
    mod = importlib.util.load_from_spec(spec)
    spec.loader.exec_module(mod)
    _argv = ['inspect_user_logs.py', args.email]
    if getattr(args, 'since', 1440) != 1440:
        _argv += ['--since', str(args.since)]
    if getattr(args, 'category', None):
        _argv += ['--category', args.category]
    if getattr(args, 'level', None):
        _argv += ['--level', args.level]
    if getattr(args, 'chat_id', None):
        _argv += ['--chat-id', args.chat_id]
    if getattr(args, 'follow', False):
        _argv.append('--follow')
    if getattr(args, 'verbose', False):
        _argv.append('--verbose')
    if getattr(args, 'json', False):
        _argv.append('--json')
    if getattr(args, 'prod', False):
        _argv.append('--prod')
    sys.argv = _argv
    asyncio.run(mod.main())


def _run_requests(args):
    """Delegate to inspect_last_requests.py."""
    import asyncio
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location(
        "inspect_last_requests",
        os.path.join(os.path.dirname(__file__), 'inspect_last_requests.py')
    )
    mod = importlib.util.load_from_spec(spec)
    spec.loader.exec_module(mod)
    _argv = ['inspect_last_requests.py']
    verbose = getattr(args, 'verbose', False)
    if getattr(args, 'chat_id', None):
        _argv += ['--chat-id', args.chat_id]
    if getattr(args, 'task_id', None):
        _argv += ['--task-id', args.task_id]
    if getattr(args, 'since_minutes', None):
        _argv += ['--since-minutes', str(args.since_minutes)]
    if getattr(args, 'errors_only', False):
        _argv.append('--errors-only')
    if getattr(args, 'show_prompt', None) is not None:
        _argv += ['--show-prompt', str(args.show_prompt)]
    if getattr(args, 'diff', None):
        _argv += ['--diff'] + [str(x) for x in args.diff]
    if getattr(args, 'clear', False):
        _argv.append('--clear')
    if getattr(args, 'json', False):
        _argv.append('--json')
    # Default to --list unless verbose (--summary) or output/diff requested
    if getattr(args, 'show_prompt', None) is None and not getattr(args, 'diff', None) and not getattr(args, 'clear', False):
        if verbose:
            _argv.append('--summary')
        else:
            _argv.append('--list')
    sys.argv = _argv
    asyncio.run(mod.main())


def _run_issue(args):
    """Delegate to inspect_issue.py."""
    import asyncio
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location(
        "inspect_issue",
        os.path.join(os.path.dirname(__file__), 'inspect_issue.py')
    )
    mod = importlib.util.load_from_spec(spec)
    spec.loader.exec_module(mod)
    _argv = ['inspect_issue.py']
    if getattr(args, 'issue_id', None):
        _argv.append(args.issue_id)
    if getattr(args, 'list', False):
        _argv.append('--list')
    if getattr(args, 'list_limit', 20) != 20:
        _argv += ['--list-limit', str(args.list_limit)]
    if getattr(args, 'search', None):
        _argv += ['--search', args.search]
    if getattr(args, 'include_processed', False):
        _argv.append('--include-processed')
    if getattr(args, 'verbose', False):
        _argv.append('--full-logs')
    if getattr(args, 'no_logs', False):
        _argv.append('--no-logs')
    if getattr(args, 'delete', False):
        _argv.append('--delete')
    if getattr(args, 'yes', False):
        _argv.append('--yes')
    if getattr(args, 'json', False):
        _argv.append('--json')
    sys.argv = _argv
    asyncio.run(mod.main())


def _run_replay(args):
    """Replay a full request trace from Loki by request_id."""
    import asyncio
    from debug_health import replay_request
    asyncio.run(replay_request(request_id=args.request_id))


def _run_errors(args):
    """Show top error fingerprints from Redis."""
    import asyncio
    from debug_health import show_error_fingerprints
    asyncio.run(show_error_fingerprints(top=getattr(args, 'top', 10)))


def main():
    parser = argparse.ArgumentParser(
        description="OpenMates unified debug tool (run via docker exec api python /app/backend/scripts/debug.py)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--json', action='store_true', help='Output as JSON where supported')

    subparsers = parser.add_subparsers(dest='command')

    # ─── health ───────────────────────────────────────────────────────────────
    health_p = subparsers.add_parser('health', help='System health check (Prometheus + Loki + queues)')
    health_p.add_argument('-v', '--verbose', action='store_true', help='Show detailed metrics and recent errors')
    health_p.set_defaults(func=_run_health)

    # ─── chat ─────────────────────────────────────────────────────────────────
    chat_p = subparsers.add_parser('chat', help='Inspect a chat (health summary by default)')
    chat_p.add_argument('chat_id', help='Chat UUID')
    chat_p.add_argument('-v', '--verbose', action='store_true', help='Full inspection (messages, embeds, keys, cache)')
    chat_p.add_argument('--decrypt', action='store_true', help='Decrypt embeds via Vault (local mode only)')
    chat_p.add_argument('--no-cache', dest='no_cache', action='store_true', help='Skip cache checks')
    chat_p.add_argument('--share-url', dest='share_url', help='Share URL with #key= for client-side decryption')
    chat_p.add_argument('--share-key', dest='share_key', help='Raw base64 key blob')
    chat_p.add_argument('--share-password', dest='share_password', help='Share link password')
    chat_p.add_argument('--prod', action='store_true', help='Fetch from production Admin Debug API')
    chat_p.add_argument('--dev', action='store_true', help='Use dev API (with --prod)')
    chat_p.add_argument('--messages-limit', dest='messages_limit', type=int, default=20)
    chat_p.add_argument('--embeds-limit', dest='embeds_limit', type=int, default=20)
    chat_p.set_defaults(func=_run_chat)

    # ─── embed ────────────────────────────────────────────────────────────────
    embed_p = subparsers.add_parser('embed', help='Inspect an embed (health summary by default)')
    embed_p.add_argument('embed_id', help='Embed UUID')
    embed_p.add_argument('-v', '--verbose', action='store_true', help='Full inspection (decode, linkage, cache)')
    embed_p.add_argument('--decrypt', action='store_true', help='Decrypt + TOON-decode content (local mode only)')
    embed_p.add_argument('--check-links', dest='check_links', action='store_true', help='Verify linkage integrity (local only)')
    embed_p.add_argument('--share-url', dest='share_url', help='Share URL with #key= for client-side decryption')
    embed_p.add_argument('--share-key', dest='share_key', help='Raw base64 key blob')
    embed_p.add_argument('--prod', action='store_true', help='Fetch from production Admin Debug API')
    embed_p.add_argument('--dev', action='store_true', help='Use dev API (with --prod)')
    embed_p.set_defaults(func=_run_embed)

    # ─── user ─────────────────────────────────────────────────────────────────
    user_p = subparsers.add_parser('user', help='Inspect a user (health summary by default)')
    user_p.add_argument('email', help='User email address')
    user_p.add_argument('-v', '--verbose', action='store_true', help='Full inspection (all items, cache, daily inspiration)')
    user_p.add_argument('--no-cache', dest='no_cache', action='store_true', help='Skip cache checks')
    user_p.add_argument('--recent-limit', dest='recent_limit', type=int, default=5)
    user_p.set_defaults(func=_run_user)

    # ─── logs ─────────────────────────────────────────────────────────────────
    logs_p = subparsers.add_parser('logs', help='User activity log timeline (Loki)')
    logs_p.add_argument('email', help='User email address')
    logs_p.add_argument('--since', type=int, default=1440, help='Minutes to look back (default: 1440 = 24h)')
    logs_p.add_argument('--category', help='Filter by category: auth,chat,sync,embed,usage,settings,client,error')
    logs_p.add_argument('--level', choices=['debug', 'info', 'warning', 'error'], help='Minimum log level')
    logs_p.add_argument('--chat-id', dest='chat_id', help='Filter by specific chat ID')
    logs_p.add_argument('--follow', action='store_true', help='Poll every 5s (Ctrl+C to stop)')
    logs_p.add_argument('-v', '--verbose', action='store_true', help='Show raw log lines alongside parsed events')
    logs_p.add_argument('--prod', action='store_true', help='Query production via Admin Debug API')
    logs_p.set_defaults(func=_run_logs)

    # ─── requests ─────────────────────────────────────────────────────────────
    req_p = subparsers.add_parser('requests', help='Recent AI requests (admin only, last 20)')
    req_p.add_argument('-v', '--verbose', action='store_true', help='Detailed summary with stats (vs quick list)')
    req_p.add_argument('--chat-id', dest='chat_id', help='Filter by chat ID')
    req_p.add_argument('--task-id', dest='task_id', help='Filter by task ID')
    req_p.add_argument('--since-minutes', dest='since_minutes', type=int, help='Only last N minutes')
    req_p.add_argument('--errors-only', dest='errors_only', action='store_true', help='Only entries with errors')
    req_p.add_argument('--show-prompt', dest='show_prompt', type=int, metavar='N', help='Print full system prompt for entry #N')
    req_p.add_argument('--diff', nargs=2, type=int, metavar=('N', 'M'), help='Diff system prompts of entries #N and #M')
    req_p.add_argument('--clear', action='store_true', help='Clear all cached debug request data')
    req_p.set_defaults(func=_run_requests)

    # ─── issue ────────────────────────────────────────────────────────────────
    issue_p = subparsers.add_parser('issue', help='Inspect issue reports')
    issue_p.add_argument('issue_id', nargs='?', help='Issue UUID (omit with --list to list all)')
    issue_p.add_argument('-v', '--verbose', action='store_true', help='Show full log output (untruncated)')
    issue_p.add_argument('--list', action='store_true', help='List recent issues')
    issue_p.add_argument('--list-limit', dest='list_limit', type=int, default=20)
    issue_p.add_argument('--search', help='Search in title/description (with --list)')
    issue_p.add_argument('--include-processed', dest='include_processed', action='store_true')
    issue_p.add_argument('--no-logs', dest='no_logs', action='store_true', help='Skip S3 YAML report fetch')
    issue_p.add_argument('--delete', action='store_true', help='Delete the issue after it is confirmed fixed')
    issue_p.add_argument('--yes', action='store_true', help='Skip confirmation for --delete')
    issue_p.set_defaults(func=_run_issue)

    # ─── replay ───────────────────────────────────────────────────────────────
    replay_p = subparsers.add_parser('replay', help='Replay full request trace from Loki by request_id')
    replay_p.add_argument('request_id', help='Request ID (from X-Request-ID header or logs)')
    replay_p.set_defaults(func=_run_replay)

    # ─── errors ───────────────────────────────────────────────────────────────
    errors_p = subparsers.add_parser('errors', help='Top error fingerprints (from Redis + Loki samples)')
    errors_p.add_argument('--top', type=int, default=10, help='Number of top errors to show (default: 10)')
    errors_p.set_defaults(func=_run_errors)

    args = parser.parse_args()

    if args.command is None:
        # No subcommand → run quick health check
        import asyncio
        from debug_health import run_health_check
        asyncio.run(run_health_check(verbose=False))
        return

    if not hasattr(args, 'func'):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
