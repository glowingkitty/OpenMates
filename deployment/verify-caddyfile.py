#!/usr/bin/env python3
"""
deployment/verify-caddyfile.py

Verify that a Caddyfile's path matchers cover all FastAPI routes,
and that every reverse_proxy port maps to an expected service.

Usage:
    python3 deployment/verify-caddyfile.py                          # auto-detect (dev or prod)
    python3 deployment/verify-caddyfile.py deployment/prod_server/Caddyfile
    python3 deployment/verify-caddyfile.py deployment/dev_server/Caddyfile
"""

import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Expected ports → services (OpenMates API servers only)
# ---------------------------------------------------------------------------
EXPECTED_PORTS = {
    8000: "api (FastAPI gateway)",
}

# FastAPI router prefixes registered in backend/core/api/main.py.
# Each entry: (prefix, description, internal_only)
# internal_only=True means the route should NOT be exposed in the Caddyfile.
FASTAPI_ROUTES = [
    ("/health", "Health check (root)", False),
    ("/v1/health", "Health check (v1)", False),
    ("/v1/server", "Server info", False),
    ("/v1/status", "Status page API", False),
    ("/v1/auth", "Authentication", False),
    ("/v1/email", "Email template previews (dev-only, no auth)", True),
    ("/v1/invoice", "Invoice PDF previews (dev-only, no auth)", True),
    ("/v1/credit-note", "Credit note PDF previews (dev-only, no auth)", True),
    ("/v1/payments", "Payments", False),
    ("/v1/ws", "WebSocket", False),
    ("/v1/apps", "Apps (public + webapp)", False),
    ("/v1/share", "Share endpoints", False),
    ("/v1/demo", "Demo chat", False),
    ("/v1/admin", "Admin endpoints", False),
    ("/v1/settings", "Settings", False),
    ("/v1/tasks", "Tasks API", False),
    ("/v1/embeds", "Embeds API", False),
    ("/v1/geocode", "Geocode proxy", False),
    ("/v1/analytics", "Analytics beacon", False),
    ("/v1/default-inspirations", "Default inspirations", False),
    ("/v1/daily-inspirations", "Daily inspirations", False),
    ("/v1/newsletter", "Newsletter", False),
    ("/v1/block-email", "Email blocking", False),
    ("/v1/debug", "Debug sync", False),
    ("/v1/docs", "Public docs API", False),
    ("/v1/push", "Push notifications", False),
    ("/v1/telemetry", "OTLP telemetry proxy", False),
    ("/v1/webhooks", "Webhooks", False),
    ("/v1/users", "Profile image API", False),
    ("/v1/creators", "Creators API", False),
    ("/v1/skills", "Skills API", False),
    ("/v1/settings/usage", "Usage API", False),
    ("/v1/settings/software_update", "Software update settings", False),
    ("/e2e", "E2E test endpoints", False),
    ("/docs", "Swagger UI", False),
    ("/openapi.json", "OpenAPI schema", False),
    # Internal-only routes — should NOT be exposed externally (except CI tunnel on dev)
    ("/internal", "Internal service-to-service API", True),
    ("/internal/tunnel", "CI tunnel management (dev only)", True),
]

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"


def extract_api_block(content: str) -> str:
    """Extract only the api.openmates.org or api.dev.openmates.org block.

    Skips other domain blocks (penpot, jupyter, etherpad, etc.) so their
    ports and paths don't pollute the verification.
    """
    # Find the start of the API domain block
    match = re.search(r'^(api\.(?:dev\.)?openmates\.org)\s*\{', content, re.MULTILINE)
    if not match:
        return content  # Fallback: use entire file

    start = match.start()
    # Track brace depth to find the matching closing brace
    depth = 0
    pos = content.index('{', start)
    for i in range(pos, len(content)):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                return content[start:i + 1]
    return content[start:]  # Fallback: rest of file


def parse_caddyfile_paths(content: str) -> set[str]:
    """Extract all path patterns from matchers and path directives."""
    api_block = extract_api_block(content)
    paths = set()
    # Match `path /foo /bar /baz` in matcher blocks and inline matchers
    for match in re.finditer(r'\bpath\s+(.+?)(?:\n|$)', api_block):
        line = match.group(1).strip()
        # Remove trailing comments
        line = re.sub(r'#.*$', '', line).strip()
        for token in line.split():
            if token.startswith('/'):
                paths.add(token)
    return paths


def parse_caddyfile_ports(content: str) -> set[int]:
    """Extract all reverse_proxy localhost:PORT ports from the API block only."""
    api_block = extract_api_block(content)
    ports = set()
    for match in re.finditer(r'reverse_proxy\s+localhost:(\d+)', api_block):
        ports.add(int(match.group(1)))
    return ports


def detect_server_type(caddyfile_path: str) -> str:
    """Detect if this is a dev or prod Caddyfile."""
    content = Path(caddyfile_path).read_text()
    if "dev.openmates.org" in content:
        return "dev"
    return "prod"


def path_is_covered(route_prefix: str, caddy_paths: set[str]) -> bool:
    """Check if a FastAPI route prefix is covered by any Caddy path matcher."""
    for caddy_path in caddy_paths:
        # Exact match
        if route_prefix == caddy_path:
            return True
        # Wildcard match: /v1/auth/* covers /v1/auth
        if caddy_path.endswith('/*'):
            base = caddy_path[:-2]  # /v1/auth
            if route_prefix == base or route_prefix.startswith(base + '/'):
                return True
        # The route is a sub-path of a covered wildcard
        # e.g. /v1/settings/usage is covered by /v1/settings/*
        if caddy_path.endswith('/*'):
            base = caddy_path[:-2]
            if route_prefix.startswith(base + '/'):
                return True
        # Route prefix covers the caddy path
        # e.g. route /v1/settings covers caddy /v1/settings/*
        if route_prefix == caddy_path.rstrip('/*'):
            return True
    return False


def main():
    # Determine Caddyfile path
    if len(sys.argv) > 1:
        caddyfile_path = sys.argv[1]
    else:
        # Auto-detect: prefer prod, fall back to dev
        root = Path(__file__).parent.parent
        prod = root / "deployment" / "prod_server" / "Caddyfile"
        dev = root / "deployment" / "dev_server" / "Caddyfile"
        if prod.exists():
            caddyfile_path = str(prod)
        elif dev.exists():
            caddyfile_path = str(dev)
        else:
            print(f"{RED}No Caddyfile found in deployment/prod_server/ or deployment/dev_server/{RESET}")
            sys.exit(1)

    path = Path(caddyfile_path)
    if not path.exists():
        print(f"{RED}Caddyfile not found: {caddyfile_path}{RESET}")
        sys.exit(1)

    content = path.read_text()
    server_type = detect_server_type(caddyfile_path)

    print(f"{BOLD}{BLUE}=== Caddyfile Verification ==={RESET}")
    print(f"File: {path}")
    print(f"Server: {server_type}")
    print()

    issues = []

    # --- Check 1: Ports ---
    print(f"{BOLD}[1] Reverse proxy ports{RESET}")
    caddy_ports = parse_caddyfile_ports(content)

    for port in sorted(caddy_ports):
        if port in EXPECTED_PORTS:
            print(f"  {GREEN}OK{RESET}  localhost:{port} -> {EXPECTED_PORTS[port]}")
        else:
            msg = f"Unexpected port localhost:{port} — no known service"
            print(f"  {RED}!!{RESET}  {msg}")
            issues.append(msg)

    for port, svc in sorted(EXPECTED_PORTS.items()):
        if port not in caddy_ports:
            msg = f"Missing port localhost:{port} ({svc}) — expected but not in Caddyfile"
            print(f"  {YELLOW}??{RESET}  {msg}")
            issues.append(msg)

    print()

    # --- Check 2: Route coverage ---
    print(f"{BOLD}[2] FastAPI route coverage{RESET}")
    caddy_paths = parse_caddyfile_paths(content)

    covered = []
    uncovered = []
    internal_exposed = []

    for prefix, desc, internal_only in FASTAPI_ROUTES:
        is_covered = path_is_covered(prefix, caddy_paths)

        if internal_only:
            # Special case: /internal/tunnel is allowed on dev via @ci_tunnel matcher
            if prefix == "/internal/tunnel" and server_type == "dev":
                # Check if specifically the CI tunnel paths are exposed
                ci_tunnel_covered = (
                    "/internal/tunnel/open" in caddy_paths
                    or "/internal/tunnel/close" in caddy_paths
                )
                if ci_tunnel_covered:
                    print(f"  {GREEN}OK{RESET}  {prefix:40s} {desc} (CI tunnel — dev only)")
                    covered.append(prefix)
                continue
            if prefix == "/internal" and server_type == "dev":
                # /internal broadly should NOT be exposed, but /internal/tunnel/* is OK
                if not is_covered:
                    print(f"  {GREEN}OK{RESET}  {prefix:40s} {desc} (blocked — correct)")
                    continue
            if is_covered:
                msg = f"{prefix} ({desc}) is internal but exposed in Caddyfile"
                print(f"  {RED}!!{RESET}  {prefix:40s} {msg}")
                internal_exposed.append(msg)
                issues.append(msg)
            else:
                print(f"  {GREEN}OK{RESET}  {prefix:40s} {desc} (blocked — correct)")
            continue

        if is_covered:
            print(f"  {GREEN}OK{RESET}  {prefix:40s} {desc}")
            covered.append(prefix)
        else:
            msg = f"{prefix} ({desc}) — not reachable through Caddyfile"
            print(f"  {RED}!!{RESET}  {prefix:40s} {desc} — NOT COVERED")
            uncovered.append(prefix)
            issues.append(msg)

    print()

    # --- Check 3: Caddy paths with no matching FastAPI route ---
    print(f"{BOLD}[3] Caddy paths without matching FastAPI route{RESET}")
    route_prefixes = {r[0] for r in FASTAPI_ROUTES}
    orphan_count = 0

    for caddy_path in sorted(caddy_paths):
        base = caddy_path.rstrip('/*')
        # Check if any FastAPI route starts with this base or matches exactly
        has_route = any(
            rp == base or rp.startswith(base + '/') or base.startswith(rp + '/')
            or (rp == base.rstrip('/'))
            for rp in route_prefixes
        )
        if not has_route:
            # Some paths are sub-paths of known routes (e.g., /v1/embeds/presigned-url under /v1/embeds)
            has_parent = any(
                base.startswith(rp + '/') or base == rp
                for rp in route_prefixes
            )
            if not has_parent:
                print(f"  {YELLOW}??{RESET}  {caddy_path} — no matching FastAPI router")
                orphan_count += 1

    if orphan_count == 0:
        print(f"  {GREEN}OK{RESET}  All Caddy paths map to known FastAPI routes")

    print()

    # --- Summary ---
    print(f"{BOLD}=== Summary ==={RESET}")
    print(f"  Routes covered:  {GREEN}{len(covered)}{RESET}")
    if uncovered:
        print(f"  Routes missing:  {RED}{len(uncovered)}{RESET}")
    if internal_exposed:
        print(f"  Internal leaked: {RED}{len(internal_exposed)}{RESET}")
    print(f"  Issues found:    {RED if issues else GREEN}{len(issues)}{RESET}")
    print()

    if issues:
        print(f"{RED}{BOLD}FAIL{RESET} — {len(issues)} issue(s) found:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}PASS{RESET} — Caddyfile matches expected configuration")
        sys.exit(0)


if __name__ == "__main__":
    main()
