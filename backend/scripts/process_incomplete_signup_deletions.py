#!/usr/bin/env python3
"""
Purpose: Preview or canary-run incomplete-signup deletion reminders without waiting for Celery Beat.
"""

import argparse
import json
import logging
import sys


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or run incomplete-signup deletion reminders/deletions.",
        epilog=(
            "Examples:\n"
            "  Preview tomorrow: docker exec api python /app/backend/scripts/process_incomplete_signup_deletions.py --dry-run\n"
            "  Send first 2 due emails: docker exec api python /app/backend/scripts/process_incomplete_signup_deletions.py --send --max-actions 2 --confirm-send"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Evaluate due work without sending emails or deleting users")
    mode.add_argument("--send", action="store_true", help="Send/delete due work now; requires --confirm-send and --max-actions")
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=1,
        help="Evaluate as if the run happened this many days from now (default: 1 for tomorrow)",
    )
    parser.add_argument("--max-users", type=int, default=None, help="Optional maximum number of users to scan")
    parser.add_argument("--max-actions", type=int, default=None, help="Stop after this many sends/deletions")
    parser.add_argument("--confirm-send", action="store_true", help="Required with --send to avoid accidental bulk delivery")
    parser.add_argument("--json", action="store_true", help="Print raw JSON stats instead of the human-readable summary")
    parser.add_argument("--verbose", action="store_true", help="Show INFO logs from the underlying services")
    return parser.parse_args()


def _format_count(count: int, label: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {label}{suffix}"


def _format_summary(result: dict, *, dry_run: bool) -> str:
    actions = {
        "14-day reminder emails": int(result.get("sent_14d") or 0),
        "7-day reminder emails": int(result.get("sent_7d") or 0),
        "1-day final reminder emails": int(result.get("sent_1d") or 0),
        "account deletions": int(result.get("deleted") or 0),
    }
    total_actions = sum(actions.values())
    action_word = "would happen" if dry_run else "were completed"
    title = "Incomplete Signup Deletion Preview" if dry_run else "Incomplete Signup Deletion Run"
    lines = [title, ""]
    lines.append(f"Checked {_format_count(int(result.get('checked') or 0), 'incomplete signup')}.")

    if total_actions:
        verb = "would happen" if dry_run else ("was completed" if total_actions == 1 else "were completed")
        lines.append(f"{_format_count(total_actions, 'action')} {verb}:")
        for label, count in actions.items():
            if count:
                lines.append(f"- {count} {label}")
    else:
        lines.append(f"No emails or deletions {action_word}.")

    skipped_not_due = int(result.get("skipped_not_due") or 0)
    skipped_safety_completed = int(result.get("skipped_safety_completed") or 0)
    skipped_missing_email = int(result.get("skipped_missing_email") or 0)
    if skipped_not_due or skipped_safety_completed or skipped_missing_email:
        lines.extend(["", "Skipped:"])
        if skipped_not_due:
            lines.append(f"- {skipped_not_due} not due yet")
        if skipped_safety_completed:
            lines.append(f"- {skipped_safety_completed} purchased credits or redeemed a gift card")
        if skipped_missing_email:
            lines.append(f"- {skipped_missing_email} had no decryptable email address")

    delete_failed = int(result.get("delete_failed") or 0)
    if delete_failed:
        lines.extend(["", f"Warning: {_format_count(delete_failed, 'deletion')} failed."])

    stopped_by_limit = result.get("stopped_by_limit")
    if stopped_by_limit:
        lines.extend(["", f"Stopped early because {stopped_by_limit} was reached."])

    if dry_run:
        days_ahead = int(result.get("days_ahead") or 0)
        when = "tomorrow" if days_ahead == 1 else f"{days_ahead} days from now"
        lines.extend(["", f"This was a dry run for {when}; nothing was sent or deleted."])
    else:
        lines.extend(["", "This was a real send/delete run."])

    lines.append("Use --json for the raw counters.")
    return "\n".join(lines)


def _configure_logging(verbose: bool) -> None:
    log_level = logging.INFO if verbose else logging.ERROR
    root = logging.getLogger()
    loggers = [root]
    loggers.extend(
        logger for logger in logging.Logger.manager.loggerDict.values() if isinstance(logger, logging.Logger)
    )
    for logger in loggers:
        for handler in list(logger.handlers):
            stream = getattr(handler, "stream", None)
            if getattr(stream, "closed", False):
                logger.removeHandler(handler)
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(handler)
    root.setLevel(log_level)
    for logger in loggers:
        if logger is not root:
            logger.setLevel(logging.NOTSET)
        for handler in logger.handlers:
            handler.setLevel(log_level)
    if not verbose:
        logging.getLogger("CSSUTILS").disabled = True


def _load_task(verbose: bool):
    if verbose:
        from backend.core.api.app.tasks.email_tasks.incomplete_signup_deletion_task import process_incomplete_signup_deletions

        return process_incomplete_signup_deletions

    logging.disable(logging.CRITICAL)
    try:
        from backend.core.api.app.tasks.email_tasks.incomplete_signup_deletion_task import process_incomplete_signup_deletions
    finally:
        logging.disable(logging.NOTSET)
    return process_incomplete_signup_deletions


def main() -> int:
    args = _parse_args()
    _configure_logging(args.verbose)

    process_incomplete_signup_deletions = _load_task(args.verbose)
    _configure_logging(args.verbose)

    if args.send:
        if not args.confirm_send:
            raise SystemExit("Refusing to send without --confirm-send")
        if args.max_actions is None or args.max_actions < 1:
            raise SystemExit("Refusing to send without --max-actions N (N >= 1)")

    result = process_incomplete_signup_deletions(
        dry_run=args.dry_run,
        max_users=args.max_users,
        max_actions=args.max_actions,
        days_ahead=args.days_ahead,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(_format_summary(result, dry_run=args.dry_run))
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
