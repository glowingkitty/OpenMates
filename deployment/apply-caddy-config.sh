#!/bin/bash
#
# Script to validate, copy, and apply Caddy configuration
# Usage: sudo deployment/apply-caddy-config.sh [path-to-caddyfile]
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

# Default Caddyfile paths (checked in order)
DEFAULT_DEV_CADDYFILE="$SCRIPT_DIR/dev_server/Caddyfile"
DEFAULT_CADDYFILE="$SCRIPT_DIR/Caddyfile"

# System Caddyfile location
SYSTEM_CADDYFILE="/etc/caddy/Caddyfile"

# Determine which Caddyfile to use
if [ -n "$1" ]; then
    # Use provided path
    CADDYFILE_PATH="$1"
elif [ -f "$DEFAULT_DEV_CADDYFILE" ]; then
    # Use dev_server Caddyfile (default)
    CADDYFILE_PATH="$DEFAULT_DEV_CADDYFILE"
elif [ -f "$DEFAULT_CADDYFILE" ]; then
    # Fall back to deployment/Caddyfile
    CADDYFILE_PATH="$DEFAULT_CADDYFILE"
else
    echo -e "${RED}Error: No Caddyfile found${NC}"
    echo -e "${YELLOW}Checked locations:${NC}"
    echo "  - $DEFAULT_DEV_CADDYFILE"
    echo "  - $DEFAULT_CADDYFILE"
    echo ""
    echo "Usage: sudo $0 [path-to-caddyfile]"
    exit 1
fi

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
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
echo -e "Source: ${GREEN}$CADDYFILE_PATH${NC}"
echo -e "Target: ${GREEN}$SYSTEM_CADDYFILE${NC}"
echo ""

# Step 1: Validate Caddyfile syntax
echo -e "${BLUE}[1/3] Validating Caddyfile syntax...${NC}"
if caddy validate --config "$CADDYFILE_PATH" --adapter caddyfile 2>&1; then
    echo -e "${GREEN}✓ Caddyfile syntax is valid${NC}"
else
    echo -e "${RED}✗ Caddyfile validation failed${NC}"
    echo -e "${YELLOW}Note: Permission errors on log files are expected and can be ignored${NC}"
    echo -e "${YELLOW}The actual syntax validation passed if you see 'adapted config to JSON'${NC}"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${RED}Aborted${NC}"
        exit 1
    fi
fi
echo ""

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
            exit 1
        fi
    fi
else
    echo -e "Service is stuck or inactive. Attempting ${BLUE}restart${NC}..."
    if systemctl restart caddy; then
        echo -e "${GREEN}✓ Caddy restarted successfully${NC}"
    else
        echo -e "${RED}✗ Failed to restart Caddy${NC}"
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
