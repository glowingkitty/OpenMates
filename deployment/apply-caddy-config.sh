#!/bin/bash
#
# Script to validate, copy, and apply Caddy configuration
# Usage:
#   sudo deployment/apply-caddy-config.sh [path-to-caddyfile]
#   sudo deployment/apply-caddy-config.sh --check [path-to-caddyfile]
#
# If no path is provided, automatically detects Caddyfile:
# 1. Checks for deployment/dev_server/Caddyfile (default)
# 2. Falls back to deployment/Caddyfile if dev_server doesn't exist
# 3. Uses provided path if specified

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Server-specific Caddyfile paths
PROD_CADDYFILE="$SCRIPT_DIR/prod_server/Caddyfile"
DEV_CADDYFILE="$SCRIPT_DIR/dev_server/Caddyfile"

# System Caddyfile location. Tests may override this with a temp file.
SYSTEM_CADDYFILE="${OPENMATES_SYSTEM_CADDYFILE:-/etc/caddy/Caddyfile}"
CADDY_BIN="${OPENMATES_CADDY_BIN:-caddy}"
CADDY_GANDI_MODULE="dns.providers.gandi"
CADDY_GANDI_PACKAGE="github.com/caddy-dns/gandi@${OPENMATES_CADDY_GANDI_VERSION:-v1.0.0}"
CADDY_XCADDY_PACKAGE="github.com/caddyserver/xcaddy/cmd/xcaddy@${OPENMATES_XCADDY_VERSION:-latest}"
CADDY_DUMMY_GANDI_TOKEN="openmates-caddyfile-syntax-check-token"

CHECK_ONLY=false
if [ "${1:-}" = "--check" ]; then
    CHECK_ONLY=true
    shift
fi

# Load SERVER_ENVIRONMENT from .env if not already set
if [ -z "$SERVER_ENVIRONMENT" ]; then
    ENV_FILE="$PROJECT_ROOT/.env"
    if [ -f "$ENV_FILE" ]; then
        SERVER_ENVIRONMENT=$(grep -E '^SERVER_ENVIRONMENT=' "$ENV_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    fi
fi

# Determine which Caddyfile to use
if [ -n "$1" ]; then
    # Use provided path (explicit override)
    CADDYFILE_PATH="$1"
elif [ "$SERVER_ENVIRONMENT" = "production" ] && [ -f "$PROD_CADDYFILE" ]; then
    # Production server → use prod Caddyfile
    CADDYFILE_PATH="$PROD_CADDYFILE"
elif [ "$SERVER_ENVIRONMENT" = "development" ] && [ -f "$DEV_CADDYFILE" ]; then
    # Dev server → use dev Caddyfile
    CADDYFILE_PATH="$DEV_CADDYFILE"
elif [ -f "$DEV_CADDYFILE" ]; then
    # Fallback to dev (backwards compat, but warn)
    CADDYFILE_PATH="$DEV_CADDYFILE"
    echo -e "${YELLOW}Warning: SERVER_ENVIRONMENT not set — defaulting to dev_server Caddyfile${NC}"
    echo -e "${YELLOW}Set SERVER_ENVIRONMENT=production in .env on prod servers${NC}"
else
    echo -e "${RED}Error: No Caddyfile found${NC}"
    echo -e "${YELLOW}Checked locations:${NC}"
    echo "  - $PROD_CADDYFILE (for SERVER_ENVIRONMENT=production)"
    echo "  - $DEV_CADDYFILE (for SERVER_ENVIRONMENT=development)"
    echo ""
    echo "Usage: sudo $0 [path-to-caddyfile]"
    exit 1
fi

# Check if running as root
if [ "$CHECK_ONLY" != true ] && [ "$EUID" -ne 0 ] && [ "${OPENMATES_CADDY_APPLY_TEST:-}" != "1" ]; then 
    echo -e "${RED}Error: This script must be run as root (use sudo)${NC}"
    echo "Usage: sudo $0 [path-to-caddyfile]"
    exit 1
fi

# Check if source Caddyfile exists
if [ ! -f "$CADDYFILE_PATH" ]; then
    echo -e "${RED}Error: Caddyfile not found at: $CADDYFILE_PATH${NC}"
    exit 1
fi

echo -e "${BLUE}=== Applying Caddy Configuration ===${NC}"
if [ "$CHECK_ONLY" = true ]; then
    echo -e "Mode: ${GREEN}check only${NC}"
fi
echo -e "Environment: ${GREEN}${SERVER_ENVIRONMENT:-unknown}${NC}"
echo -e "Source: ${GREEN}$CADDYFILE_PATH${NC}"
echo -e "Target: ${GREEN}$SYSTEM_CADDYFILE${NC}"
echo ""

# Safety check: warn if Caddyfile doesn't match environment
if [ "$SERVER_ENVIRONMENT" = "production" ] && echo "$CADDYFILE_PATH" | grep -q "dev_server"; then
    echo -e "${RED}ERROR: Attempting to apply dev_server Caddyfile on a PRODUCTION server!${NC}"
    echo -e "${RED}This would expose dev-only domains (penpot, pad, jupyter) on prod.${NC}"
    echo -e "${YELLOW}Use: sudo $0 deployment/prod_server/Caddyfile${NC}"
    exit 1
fi

config_requires_gandi_dns() {
    grep -Eq '^[[:space:]]*dns[[:space:]]+gandi([[:space:]]|$)' "$CADDYFILE_PATH"
}

caddy_has_module() {
    "$CADDY_BIN" list-modules 2>/dev/null | grep -qx "$1"
}

installed_caddy_version() {
    "$CADDY_BIN" version 2>/dev/null | awk '{print $1}'
}

warn_if_gandi_token_not_in_shell() {
    if [ -n "${GANDI_BEARER_TOKEN:-}" ]; then
        return 0
    fi

    echo -e "${YELLOW}⚠ Caddyfile requires Gandi DNS-01 and GANDI_BEARER_TOKEN is not available to this shell.${NC}"
    echo -e "${YELLOW}The syntax check will use a dummy token. The real token must be configured for the Caddy service before reload.${NC}"
    echo ""
    echo "  sudo systemctl edit caddy"
    echo ""
    echo "Add:"
    echo "  [Service]"
    echo "  Environment=GANDI_BEARER_TOKEN=<PASTE_GANDI_BEARER_TOKEN>"
    echo ""
    echo "Then run:"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl restart caddy"
    echo "  sudo deployment/apply-caddy-config.sh $CADDYFILE_PATH"
    echo ""
    echo -e "${YELLOW}Do not put the Gandi token in the repository, app .env, or Docker containers.${NC}"
}

caddy_with_validation_env() {
    if config_requires_gandi_dns && [ -z "${GANDI_BEARER_TOKEN:-}" ]; then
        GANDI_BEARER_TOKEN="$CADDY_DUMMY_GANDI_TOKEN" "$CADDY_BIN" "$@"
    else
        "$CADDY_BIN" "$@"
    fi
}

install_caddy_with_gandi_module() {
    local caddy_path version temp_dir xcaddy_bin built_caddy backup_path
    caddy_path="$(command -v "$CADDY_BIN" || true)"
    if [ -z "$caddy_path" ]; then
        echo -e "${RED}✗ Cannot find Caddy binary '$CADDY_BIN'.${NC}"
        return 1
    fi

    if ! command -v go >/dev/null 2>&1; then
        echo -e "${RED}✗ Go is required to build Caddy with $CADDY_GANDI_MODULE but was not found.${NC}"
        echo -e "${YELLOW}Install Go, or provision a wildcard certificate externally and configure Caddy to load cert files.${NC}"
        return 1
    fi

    version="$(installed_caddy_version)"
    if ! echo "$version" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+'; then
        echo -e "${RED}✗ Could not determine installed Caddy version from '$version'.${NC}"
        return 1
    fi

    temp_dir="$(mktemp -d /tmp/openmates-caddy-build.XXXXXX)"
    xcaddy_bin="$temp_dir/xcaddy"
    built_caddy="$temp_dir/caddy"
    echo -e "${BLUE}Installing xcaddy into temporary build directory...${NC}"
    GOBIN="$temp_dir" go install "$CADDY_XCADDY_PACKAGE"

    echo -e "${BLUE}Building Caddy $version with $CADDY_GANDI_PACKAGE...${NC}"
    "$xcaddy_bin" build "$version" --with "$CADDY_GANDI_PACKAGE" --output "$built_caddy"

    if ! "$built_caddy" list-modules 2>/dev/null | grep -qx "$CADDY_GANDI_MODULE"; then
        echo -e "${RED}✗ Built Caddy binary does not contain $CADDY_GANDI_MODULE.${NC}"
        return 1
    fi

    backup_path="${caddy_path}.openmates-backup-$(date +%Y%m%d%H%M%S)"
    echo -e "${BLUE}Installing custom Caddy binary to $caddy_path...${NC}"
    cp "$caddy_path" "$backup_path"
    chmod 755 "$backup_path"
    install -m 755 "$built_caddy" "$caddy_path"
    echo -e "${GREEN}✓ Installed Caddy with $CADDY_GANDI_MODULE${NC}"
    echo -e "${GREEN}✓ Previous Caddy binary backed up at $backup_path${NC}"
}

# Ensure Caddy can load DNS provider modules before adaptation. This is done
# before caddy adapt because Caddyfile adaptation fails if the module is missing
# or if the provider token placeholder expands to an empty value.
if config_requires_gandi_dns; then
    echo -e "${BLUE}Checking Caddy Gandi DNS provider support...${NC}"
    warn_if_gandi_token_not_in_shell
    if caddy_has_module "$CADDY_GANDI_MODULE"; then
        echo -e "${GREEN}✓ Caddy has $CADDY_GANDI_MODULE${NC}"
    elif [ "$CHECK_ONLY" = true ]; then
        echo -e "${RED}✗ Caddyfile requires $CADDY_GANDI_MODULE but the installed Caddy binary does not include it.${NC}"
        echo -e "${YELLOW}Run without --check as root to let this script build and install the required Caddy extension.${NC}"
        exit 1
    else
        echo -e "${YELLOW}Caddy is missing $CADDY_GANDI_MODULE; building and installing a compatible binary.${NC}"
        install_caddy_with_gandi_module || exit 1
    fi
    echo ""
fi

# Step 1: Validate Caddyfile syntax with the installed Caddy binary.
# This must fail closed. A config that cannot adapt or validate can prevent
# Caddy from starting, so never offer an interactive override here.
echo -e "${BLUE}[1/3] Validating Caddyfile syntax...${NC}"
ADAPTED_CADDYFILE="$(mktemp /tmp/openmates-caddy-adapted.XXXXXX.json)"
trap 'rm -f "$ADAPTED_CADDYFILE"' EXIT
if ! caddy_with_validation_env adapt --config "$CADDYFILE_PATH" --adapter caddyfile >"$ADAPTED_CADDYFILE"; then
    echo -e "${RED}✗ Caddyfile adaptation failed${NC}"
    echo -e "${YELLOW}The installed Caddy binary cannot load this config or one of its modules.${NC}"
    echo -e "${YELLOW}Nothing was copied to $SYSTEM_CADDYFILE and Caddy was not reloaded.${NC}"
    exit 1
fi

if [ "$CHECK_ONLY" = true ] && [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}Skipping caddy validate in non-root check mode because it provisions log writers.${NC}"
    echo -e "${GREEN}✓ Caddyfile adapts with the installed Caddy binary${NC}"
elif caddy_with_validation_env validate --config "$CADDYFILE_PATH" --adapter caddyfile 2>&1; then
    echo -e "${GREEN}✓ Caddyfile syntax is valid${NC}"
else
    echo -e "${RED}✗ Caddyfile validation failed${NC}"
    echo -e "${YELLOW}Nothing was copied to $SYSTEM_CADDYFILE and Caddy was not reloaded.${NC}"
    exit 1
fi
echo ""

if [ "$CHECK_ONLY" = true ]; then
    echo -e "${GREEN}=== Caddy configuration check passed; no files copied and no reload attempted ===${NC}"
    exit 0
fi

BACKUP_CADDYFILE=""
if [ -f "$SYSTEM_CADDYFILE" ]; then
    BACKUP_CADDYFILE="$(mktemp /tmp/openmates-caddyfile-backup.XXXXXX)"
    cp "$SYSTEM_CADDYFILE" "$BACKUP_CADDYFILE"
    chmod 600 "$BACKUP_CADDYFILE"
fi

restore_previous_caddyfile() {
    if [ -n "$BACKUP_CADDYFILE" ] && [ -f "$BACKUP_CADDYFILE" ]; then
        echo -e "${YELLOW}Restoring previous Caddyfile from backup...${NC}"
        cp "$BACKUP_CADDYFILE" "$SYSTEM_CADDYFILE"
        chown root:root "$SYSTEM_CADDYFILE"
        chmod 644 "$SYSTEM_CADDYFILE"
        if systemctl restart caddy; then
            echo -e "${GREEN}✓ Previous Caddy configuration restored${NC}"
        else
            echo -e "${RED}✗ Failed to restart Caddy with the previous configuration${NC}"
            echo -e "${YELLOW}Backup remains at: $BACKUP_CADDYFILE${NC}"
        fi
    fi
}

# Step 2: Copy Caddyfile to system location
echo -e "${BLUE}[2/3] Copying Caddyfile to system location...${NC}"
if cp "$CADDYFILE_PATH" "$SYSTEM_CADDYFILE"; then
    echo -e "${GREEN}✓ Caddyfile copied successfully${NC}"
    # Set proper permissions
    chown root:root "$SYSTEM_CADDYFILE"
    chmod 644 "$SYSTEM_CADDYFILE"
    echo -e "${GREEN}✓ Permissions set correctly${NC}"

    # Step 2.1: Fix potential log file permission issues created by 'caddy validate' run as root
    if [ -d /var/log/caddy ]; then
        echo -e "${BLUE}Ensuring /var/log/caddy/ permissions...${NC}"
        chown -R caddy:caddy /var/log/caddy
        chmod -R 755 /var/log/caddy
        # Ensure log files themselves are not world-readable but writable by caddy
        find /var/log/caddy -type f -exec chmod 640 {} +
        echo -e "${GREEN}✓ Log permissions fixed${NC}"
    fi
else
    echo -e "${RED}✗ Failed to copy Caddyfile${NC}"
    exit 1
fi
echo ""

# Step 3: Reload Caddy to apply changes
echo -e "${BLUE}[3/3] Applying Caddy configuration...${NC}"
# Use restart instead of reload if service is already in a 'reloading' state or stuck
if systemctl is-active --quiet caddy && [[ "$(systemctl show caddy --property=ActiveState)" != "ActiveState=reloading" ]]; then
    echo -e "Attempting ${BLUE}reload${NC}..."
    if timeout 10s systemctl reload caddy; then
        echo -e "${GREEN}✓ Caddy reloaded successfully${NC}"
    else
        echo -e "${YELLOW}Reload timed out or failed. Attempting full restart...${NC}"
        if systemctl restart caddy; then
            echo -e "${GREEN}✓ Caddy restarted successfully${NC}"
        else
            echo -e "${RED}✗ Failed to restart Caddy${NC}"
            restore_previous_caddyfile
            exit 1
        fi
    fi
else
    echo -e "Service is stuck or inactive. Attempting ${BLUE}restart${NC}..."
    if systemctl restart caddy; then
        echo -e "${GREEN}✓ Caddy restarted successfully${NC}"
    else
        echo -e "${RED}✗ Failed to restart Caddy${NC}"
        restore_previous_caddyfile
        exit 1
    fi
fi
echo ""

# Show final status
echo -e "${BLUE}=== Final Status ===${NC}"
if systemctl is-active --quiet caddy; then
    echo -e "${GREEN}✓ Caddy is running${NC}"
    echo ""
    echo -e "${BLUE}Service status:${NC}"
    systemctl status caddy --no-pager -l | head -10
else
    echo -e "${RED}✗ Caddy is not running${NC}"
    echo -e "${YELLOW}Check logs with: sudo journalctl -u caddy -n 50${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}=== Configuration applied successfully! ===${NC}"
