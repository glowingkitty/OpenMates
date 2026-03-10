#!/usr/bin/env python3
"""
Unified debug entry point for OpenMates backend.

All debugging goes through this single script. Each subcommand delegates to a
dedicated debug_*.py module, passing the remaining CLI arguments through.

Architecture context: See docs/claude/debugging.md
Tests: None (inspection script, not production code)

USAGE
-----
  docker exec api python /app/backend/scripts/debug.py [command] [options]

Commands:
  (none)          Quick system health check
  health          System health check (Prometheus + Loki + queues)
  chat            Inspect a chat (messages, embeds, keys, cache)
  embed           Inspect an embed (decode, linkage, cache)
  user            Inspect a user (items, cache, credits)
  logs            User timeline, browser logs, or OpenObserve summaries
  requests        Recent AI requests (admin only)
  issue           Inspect/list/delete issue reports
  newsletter      Newsletter subscriber stats
  daily           Daily inspiration state
  demo            Demo chat state
  replay          Replay a request trace from Loki
  errors          Top error fingerprints
  upload-logs     Logs from the upload server (satellite VM)
  preview-logs    Logs from the preview server (satellite VM)
  upload-update   Trigger git pull + rebuild on upload server
  preview-update  Trigger git pull + rebuild on preview server
  upload-status   Poll last update status on upload server
  preview-status  Poll last update status on preview server

Run any command with --help for full options.

Examples:
  debug.py                              # quick health check
  debug.py chat <id>                    # chat health summary
  debug.py chat <id> -v --decrypt       # full chat inspection
  debug.py logs <email> --since 60      # user activity timeline
  debug.py logs --browser --search X    # browser console logs
  debug.py logs --o2 --preset web-app-health --since 60
  debug.py requests --errors-only       # recent AI errors
  debug.py issue --list                 # list open issues
  debug.py errors --top 20             # top error fingerprints
"""

import os
import re
import sys

# ── Path bootstrap ────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
if '/app/backend' not in sys.path:
    sys.path.insert(0, '/app/backend')
if '/app' not in sys.path:
    sys.path.insert(0, '/app')


# ── Subcommand → module mapping ──────────────────────────────────────────────

COMMANDS = {
    'health':          'debug_health',
    'chat':            'debug_chat',
    'embed':           'debug_embed',
    'user':            'debug_user',
    'logs':            'debug_logs',
    'requests':        'debug_requests',
    'issue':           'debug_issue',
    'newsletter':      'debug_newsletter',
    'daily':           'debug_daily_inspiration',
    'demo':            'debug_demo_chat',
    'upload-logs':     'debug_logs',
    'preview-logs':    'debug_logs',
    'upload-update':   'debug_logs',
    'preview-update':  'debug_logs',
    'upload-status':   'debug_logs',
    'preview-status':  'debug_logs',
    'replay':          'debug_health',
    'errors':          'debug_health',
}

# Satellite commands are mode flags within debug_logs.py
_SATELLITE_FLAG = {
    'upload-logs':     '--upload-logs',
    'preview-logs':    '--preview-logs',
    'upload-update':   '--upload-update',
    'preview-update':  '--preview-update',
    'upload-status':   '--upload-status',
    'preview-status':  '--preview-status',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _delegate(module_name, argv):
    """Import a debug module and call its main() with the given argv."""
    import asyncio
    import importlib

    sys.argv = argv
    mod = importlib.import_module(module_name)
    main_fn = getattr(mod, 'main')

    if asyncio.iscoroutinefunction(main_fn):
        asyncio.run(main_fn())
    else:
        main_fn()


_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.I,
)


def _dispatch(command, rest):
    """Route a subcommand to its module."""
    if command not in COMMANDS:
        if _UUID_RE.match(command):
            print(f"Hint: did you mean 'debug.py chat {command}'"
                  f" or 'debug.py embed {command}'?")
        elif '@' in command:
            print(f"Hint: did you mean 'debug.py user {command}'?")
        else:
            print(f"Unknown command: {command}")
        print("\nRun 'debug.py --help' for available commands.")
        sys.exit(1)

    module_name = COMMANDS[command]

    if command in _SATELLITE_FLAG:
        _delegate(module_name, ['debug_logs.py', _SATELLITE_FLAG[command]] + rest)
    elif command in ('health', 'replay', 'errors'):
        _delegate(module_name, ['debug_health.py', command] + rest)
    else:
        _delegate(module_name, [f'{module_name}.py'] + rest)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args:
        import asyncio
        from debug_health import run_health_check
        asyncio.run(run_health_check(verbose=False))
        return

    if args[0] in ('-h', '--help'):
        print(__doc__.strip())
        return

    _dispatch(args[0], args[1:])


if __name__ == '__main__':
    main()
