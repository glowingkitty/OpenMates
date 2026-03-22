#!/usr/bin/env python3
"""
Render deployment config templates with values from the .env file.

Reads DEPLOY_* (and other) variables from the project root .env file,
substitutes ${VAR_NAME} placeholders in the given template, and outputs
the rendered result to stdout.

Usage:
    python scripts/render-deploy-config.py <template-path>
    python scripts/render-deploy-config.py <template-path> --env-file path/to/.env
    python scripts/render-deploy-config.py <template-path> > output-file

Examples:
    # Render cloud-init for upload server (copy output into Hetzner "User data"):
    python scripts/render-deploy-config.py deployment/upload_server/upload-cloud-config.yaml

    # Render and apply Caddyfile directly on the server:
    python scripts/render-deploy-config.py deployment/upload_server/Caddyfile \\
        | sudo tee /etc/caddy/Caddyfile > /dev/null
    sudo systemctl reload caddy

    # Use a different .env file:
    python scripts/render-deploy-config.py deployment/upload_server/Caddyfile \\
        --env-file /path/to/upload-server.env

Notes:
    - Only ${VAR_NAME} patterns are substituted (not $VAR or other formats).
    - Caddy runtime variables like {http.request.host} are NOT touched because
      they don't start with $ — only ${...} patterns are matched.
    - The script FAILS (exit 1) if any ${...} placeholders remain unresolved.
      Use --no-strict to allow unresolved placeholders and only warn.
    - Variables with empty values in .env are treated as unset (will fail).
"""

import argparse
import re
import sys
from pathlib import Path

# Pattern for our deploy placeholders: ${VAR_NAME}
# Matches ${ANYTHING_WITH_UPPERCASE_AND_UNDERSCORES}
# Does NOT match Caddy's {http.request.host} because those don't start with $
PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse a .env file into a dictionary of key=value pairs.

    Handles:
        - Lines with KEY=VALUE (with or without quotes)
        - Comments (# ...) and blank lines are skipped
        - Inline comments after values are stripped
        - Double-quoted and single-quoted values (quotes removed)
        - Lines with KEY= (empty value) are stored as empty string
    """
    env_vars: dict[str, str] = {}

    if not env_path.exists():
        print(f"Error: .env file not found at {env_path}", file=sys.stderr)
        sys.exit(1)

    for line_num, raw_line in enumerate(env_path.read_text().splitlines(), start=1):
        line = raw_line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Must contain = to be a valid env line
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()

        # Skip lines that don't look like valid env keys
        if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue

        # Strip inline comments (but not inside quotes)
        value = value.strip()
        if value and value[0] in ('"', "'"):
            # Quoted value — find matching closing quote
            quote_char = value[0]
            end_idx = value.find(quote_char, 1)
            if end_idx != -1:
                value = value[1:end_idx]
            else:
                # No closing quote — take everything after opening quote
                value = value[1:]
        else:
            # Unquoted value — strip inline comments
            comment_idx = value.find(" #")
            if comment_idx != -1:
                value = value[:comment_idx].strip()

        env_vars[key] = value

    return env_vars


def render_template(template_content: str, env_vars: dict[str, str]) -> str:
    """Substitute ${VAR_NAME} placeholders with values from env_vars.

    Returns the rendered string. Placeholders whose keys are not found
    in env_vars (or have empty values) are left as-is for the warning pass.
    """

    def replace_match(match: re.Match) -> str:
        var_name = match.group(1)
        value = env_vars.get(var_name)
        if value is not None and value != "":
            return value
        # Leave unresolved — will be caught by the warning pass
        return match.group(0)

    return PLACEHOLDER_PATTERN.sub(replace_match, template_content)


def find_unresolved(rendered: str) -> list[tuple[int, str, str]]:
    """Find any remaining ${VAR_NAME} placeholders in the rendered output.

    Returns a list of (line_number, var_name, full_line) tuples.
    """
    unresolved = []
    for line_num, line in enumerate(rendered.splitlines(), start=1):
        for match in PLACEHOLDER_PATTERN.finditer(line):
            unresolved.append((line_num, match.group(1), line.strip()))
    return unresolved


def find_project_root() -> Path:
    """Walk up from the script's location to find the project root (contains .env.example)."""
    current = Path(__file__).resolve().parent
    for _ in range(10):  # Max 10 levels up
        if (current / ".env.example").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Fallback: try current working directory
    cwd = Path.cwd()
    if (cwd / ".env.example").exists():
        return cwd

    print(
        "Error: Could not find project root (no .env.example found).", file=sys.stderr
    )
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render deployment config templates with values from .env",
        epilog="Example: python scripts/render-deploy-config.py deployment/upload_server/Caddyfile",
    )
    parser.add_argument(
        "template",
        help="Path to the template file (relative to project root or absolute)",
    )
    parser.add_argument(
        "--env-file",
        help="Path to .env file (default: project root .env)",
        default=None,
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="Allow unresolved placeholders (default is to fail on any unresolved placeholder)",
    )
    args = parser.parse_args()

    # Resolve project root and paths
    project_root = find_project_root()
    env_path = Path(args.env_file) if args.env_file else project_root / ".env"
    template_path = Path(args.template)
    if not template_path.is_absolute():
        template_path = project_root / template_path

    # Read .env
    env_vars = parse_env_file(env_path)

    # Read template
    if not template_path.exists():
        print(f"Error: Template not found at {template_path}", file=sys.stderr)
        sys.exit(1)

    template_content = template_path.read_text()

    # Render
    rendered = render_template(template_content, env_vars)

    # Check for unresolved placeholders
    unresolved = find_unresolved(rendered)
    if unresolved:
        print(
            f"WARNING: {len(unresolved)} unresolved placeholder(s) in output:",
            file=sys.stderr,
        )
        for line_num, var_name, line_text in unresolved:
            print(
                f"  Line {line_num}: ${{{var_name}}}  ({line_text})", file=sys.stderr
            )
        if not args.no_strict:
            print(
                "\nERROR: Aborting — set these variables in your .env file and re-run.",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            print(
                "\nWARNING: Continuing with unresolved placeholders (--no-strict).",
                file=sys.stderr,
            )

    # Output rendered template to stdout
    print(rendered, end="")


if __name__ == "__main__":
    main()
