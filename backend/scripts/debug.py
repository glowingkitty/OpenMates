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
  (none)          System health check (includes log access verification)
  health          System health check (log access + Prometheus + queues + recent errors)
    --log-access  Check ONLY log access (OpenObserve local + production API); exits 1 on failure
  chat            Inspect a chat (messages, embeds, keys, cache)
  embed           Inspect an embed (decode, linkage, cache)
  user            Inspect a user (items, cache, credits)
  logs            User timeline, browser logs, or OpenObserve summaries
  requests        Recent AI requests (admin only)
  issue           Inspect/list/delete issue reports
  newsletter      Newsletter subscriber stats
  daily           Daily inspiration state
  demo            Demo chat state
  replay          Replay a request trace from OpenObserve
  errors          Top error fingerprints
  issues          List recent issues with optional git commit cross-reference
    --since <H>     Look back N hours (default: 24)
    --check-commits Check if each issue ID appears in git commit history
  vercel          Fetch Vercel build logs (works for ERROR deployments via REST API)
    --all           Show full log (default: errors + warnings only)
    --url <id>      Inspect a specific deployment URL or ID
    --n <N>         Check last N deployments (default: 1)
    --max-events N  Pagination limit (default: 5000, increase if truncated)
  upload-logs     Logs from the upload server (satellite VM)
  preview-logs    Logs from the preview server (satellite VM)
  upload-update   Trigger git pull + rebuild on upload server
  preview-update  Trigger git pull + rebuild on preview server
  upload-status   Poll last update status on upload server
  preview-status  Poll last update status on preview server

Run any command with --help for full options.

Examples:
  debug.py                              # run a health check snapshot
  debug.py chat <id>                    # chat health summary
  debug.py chat <id> -v --decrypt       # full chat inspection
  debug.py logs <email> --since 60      # user activity timeline
  debug.py logs --browser --search X    # browser console logs
  debug.py logs --browser --device iphone         # iPhone-only browser logs
  debug.py logs --browser --device iphone --level error  # iPhone errors only
  debug.py logs --o2 --preset web-app-health --since 60
  debug.py logs --o2 --sql "SELECT * FROM \"default\" ORDER BY _timestamp DESC" --quiet-health
  debug.py requests --errors-only       # recent AI errors
  debug.py issue --list                 # list open issues
  debug.py errors --top 20             # top error fingerprints
  debug.py vercel                       # latest deployment errors/warnings
  debug.py vercel --all                 # latest deployment full build log
  debug.py vercel --n 3                 # last 3 deployments errors/warnings
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
    'issues':          '_builtin_issues',
    'newsletter':      'debug_newsletter',
    'daily':           'debug_daily_inspiration',
    'demo':            'debug_demo_chat',
    'vercel':          'debug_vercel',
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


def _run_builtin_issues(rest):
    """List recent issues and check if they've been addressed in git commits.

    Usage:
      debug.py issues                          # unprocessed issues from last 24h
      debug.py issues --since 72               # last 72 hours
      debug.py issues --check-commits          # also check git log for matching commits
      debug.py issues --include-processed      # include already-processed issues
    """
    import argparse as _ap
    import subprocess

    parser = _ap.ArgumentParser(prog="debug.py issues")
    parser.add_argument(
        "--since", type=int, default=24, metavar="HOURS",
        help="Look back N hours for issues (default: 24).",
    )
    parser.add_argument(
        "--check-commits", action="store_true",
        help="Check if each issue ID appears in git commit messages.",
    )
    parser.add_argument(
        "--include-processed", action="store_true",
        help="Include already-processed issues.",
    )
    args = parser.parse_args(rest)

    # Delegate to debug_issue.py for the actual issue listing
    list_args = ["debug_issue.py", "--list", "--compact", "--list-limit", "50"]
    if args.include_processed:
        list_args.append("--include-processed")

    # Run via subprocess to capture output
    cmd = [
        sys.executable, os.path.join(_SCRIPT_DIR, "debug_issue.py"),
        "--list", "--compact", "--list-limit", "50",
    ]
    if args.include_processed:
        cmd.append("--include-processed")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"Error fetching issues: {result.stderr[:300]}")
        return

    raw_output = result.stdout.strip()
    if not raw_output:
        print("No issues found.")
        return

    # Parse the compact output — lines like:
    #   #<id> (<age>) "<title>" — user:<user_id>
    issue_lines = []
    for line in raw_output.split("\n"):
        line = line.strip()
        if line.startswith("#"):
            issue_lines.append(line)

    if not issue_lines:
        print(raw_output)
        return

    # Filter by --since (parse age from output)
    since_hours = args.since
    filtered = []
    for line in issue_lines:
        # Parse age like "(20h ago)" or "(2d ago)" or "(5m ago)"
        import re as _re
        age_match = _re.search(r'\((\d+)(m|h|d)\s+ago\)', line)
        if age_match:
            val = int(age_match.group(1))
            unit = age_match.group(2)
            age_hours = val if unit == "h" else (val / 60 if unit == "m" else val * 24)
            if age_hours <= since_hours:
                filtered.append(line)
        else:
            filtered.append(line)  # Include if age can't be parsed

    if not filtered:
        print(f"No issues in the last {since_hours}h.")
        return

    # Check commits if requested
    if args.check_commits:
        print(f"Issues (last {since_hours}h) with commit check:")
        print(f"{'─' * 72}")
        for line in filtered:
            # Extract issue ID
            import re as _re
            id_match = _re.match(r'#([a-f0-9]+)', line)
            issue_id = id_match.group(1) if id_match else None

            commit_info = ""
            if issue_id:
                try:
                    git_result = subprocess.run(
                        ["git", "log", "--all", "--oneline", "--grep", issue_id],
                        capture_output=True, text=True, timeout=10,
                        cwd=os.path.join(_SCRIPT_DIR, "..", ".."),
                    )
                    commits = git_result.stdout.strip()
                    if commits:
                        first_commit = commits.split("\n")[0]
                        commit_info = f"  ADDRESSED: {first_commit}"
                    else:
                        commit_info = "  UNADDRESSED"
                except Exception:
                    commit_info = "  (git check failed)"

            print(f"  {line}")
            if commit_info:
                print(f"    {commit_info}")
    else:
        print(f"Issues (last {since_hours}h):")
        for line in filtered:
            print(f"  {line}")
        print()
        print("  Tip: add --check-commits to see if issues are addressed in git history")


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

    # Built-in commands that don't delegate to a module
    if module_name == '_builtin_issues':
        _run_builtin_issues(rest)
        return

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
        print((__doc__ or "").strip())
        return

    _dispatch(args[0], args[1:])


if __name__ == '__main__':
    main()
