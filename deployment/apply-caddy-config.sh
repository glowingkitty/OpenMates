#!/bin/bash
#
# Script to validate, copy, and apply Caddy configuration
# Usage:
#   sudo deployment/apply-caddy-config.sh [path-to-caddyfile]
#   sudo deployment/apply-caddy-config.sh --check [path-to-caddyfile]
#   sudo deployment/apply-caddy-config.sh --set-gandi-token [token]
#   sudo deployment/apply-caddy-config.sh --rotate-gandi-token [token]
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
REQUIRED_CADDY_VERSION="${OPENMATES_CADDY_VERSION:-v2.10.2}"
REQUIRED_CADDY_GANDI_VERSION="${OPENMATES_CADDY_GANDI_VERSION:-v1.1.0}"
REQUIRED_LIBDNS_GANDI_VERSION="${OPENMATES_LIBDNS_GANDI_VERSION:-v1.1.0}"
CADDY_GANDI_PACKAGE="github.com/caddy-dns/gandi@${REQUIRED_CADDY_GANDI_VERSION}"
CADDY_XCADDY_PACKAGE="github.com/caddyserver/xcaddy/cmd/xcaddy@${OPENMATES_XCADDY_VERSION:-latest}"
CADDY_DUMMY_GANDI_TOKEN="openmates-caddyfile-syntax-check-token"
CADDY_SERVICE_ENV_FILE="${OPENMATES_CADDY_SERVICE_ENV_FILE:-/etc/caddy/openmates-gandi.env}"
CADDY_SERVICE_DROPIN="${OPENMATES_CADDY_SERVICE_DROPIN:-/etc/systemd/system/caddy.service.d/openmates-gandi-token.conf}"
CADDY_SERVICE_NO_ENVIRON_DROPIN="${OPENMATES_CADDY_SERVICE_NO_ENVIRON_DROPIN:-/etc/systemd/system/caddy.service.d/openmates-no-environ.conf}"
AUTO_INSTALL_PREREQS="${OPENMATES_CADDY_AUTO_INSTALL_PREREQS:-}"
REQUIRED_GO_MIN_VERSION="${OPENMATES_CADDY_GO_MIN_VERSION:-1.24.0}"
GO_INSTALL_VERSION="${OPENMATES_CADDY_GO_VERSION:-1.26.4}"
GO_INSTALL_ROOT="${OPENMATES_CADDY_GO_INSTALL_ROOT:-/usr/local}"
GO_LINUX_AMD64_SHA256="1153d3d50e0ac764b447adfe05c2bcf08e889d42a02e0fe0259bd47f6733ad7f"
GO_LINUX_ARM64_SHA256="ef758ae7c6cf9267c9c0ef080b8965f453d89ab2d25d9eb22de4405925238768"

CHECK_ONLY=false
SET_GANDI_TOKEN_ONLY=false
GANDI_TOKEN_ARG=""
if [ "${1:-}" = "--check" ]; then
    CHECK_ONLY=true
    shift
fi
if [ "${1:-}" = "--set-gandi-token" ] || [ "${1:-}" = "--rotate-gandi-token" ]; then
    SET_GANDI_TOKEN_ONLY=true
    shift
    GANDI_TOKEN_ARG="${1:-}"
    if [ -n "${1:-}" ]; then
        shift
    fi
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
if [ "$SET_GANDI_TOKEN_ONLY" != true ] && [ ! -f "$CADDYFILE_PATH" ]; then
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

caddy_build_info_has_dependency() {
    local module="$1" version="$2"
    "$CADDY_BIN" build-info 2>/dev/null \
        | grep -Eq "[[:space:]]${module//\//\/}[[:space:]]+${version//./\.}([[:space:]]|$)"
}

caddy_gandi_module_is_compatible() {
    caddy_has_module "$CADDY_GANDI_MODULE" || return 1
    caddy_build_info_has_dependency "github.com/caddy-dns/gandi" "$REQUIRED_CADDY_GANDI_VERSION" || return 1
    caddy_build_info_has_dependency "github.com/libdns/gandi" "$REQUIRED_LIBDNS_GANDI_VERSION" || return 1
}

caddy_gandi_module_status() {
    if ! caddy_has_module "$CADDY_GANDI_MODULE"; then
        echo "missing"
    elif ! caddy_gandi_module_is_compatible; then
        echo "stale"
    else
        echo "compatible"
    fi
}

installed_caddy_version() {
    "$CADDY_BIN" version 2>/dev/null | awk '{print $1}'
}

version_ge() {
    local current="${1#v}" required="${2#v}"
    current="${current#go}"
    required="${required#go}"
    [ "$(printf '%s\n%s\n' "$required" "$current" | sort -V | head -n1)" = "$required" ]
}

is_truthy() {
    case "${1:-}" in
        1|true|TRUE|yes|YES|y|Y)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

go_is_available() {
    if [ "${OPENMATES_CADDY_APPLY_TEST_GO_MISSING:-}" = "1" ]; then
        return 1
    fi
    command -v go >/dev/null 2>&1 && version_ge "$(go env GOVERSION 2>/dev/null || go version | awk '{print $3}')" "$REQUIRED_GO_MIN_VERSION"
}

describe_go_install_command() {
    echo "Install Go ${GO_INSTALL_VERSION} from go.dev into ${GO_INSTALL_ROOT}/go"
}

run_go_install_command() {
    local goos goarch tarball url expected_sha temp_dir
    goos="$(go env GOOS 2>/dev/null || uname | tr '[:upper:]' '[:lower:]')"
    goarch="$(go env GOARCH 2>/dev/null || uname -m)"
    case "$goarch" in
        x86_64) goarch="amd64" ;;
        aarch64) goarch="arm64" ;;
    esac
    if [ "$goos" != "linux" ]; then
        echo -e "${RED}✗ Automatic Go install currently supports Linux only (detected $goos).${NC}"
        return 1
    fi
    case "$goarch" in
        amd64) expected_sha="$GO_LINUX_AMD64_SHA256" ;;
        arm64) expected_sha="$GO_LINUX_ARM64_SHA256" ;;
        *)
            echo -e "${RED}✗ Automatic Go install supports amd64/arm64 only (detected $goarch).${NC}"
            return 1
            ;;
    esac
    if ! command -v curl >/dev/null 2>&1; then
        echo -e "${RED}✗ curl is required to install Go from go.dev.${NC}"
        return 1
    fi
    temp_dir="$(mktemp -d /tmp/openmates-go-install.XXXXXX)"
    tarball="go${GO_INSTALL_VERSION}.linux-${goarch}.tar.gz"
    url="https://go.dev/dl/${tarball}"
    echo -e "${BLUE}Downloading $url...${NC}"
    curl -fsSLo "$temp_dir/$tarball" "$url"
    printf '%s  %s\n' "$expected_sha" "$temp_dir/$tarball" | sha256sum -c -
    rm -rf "$GO_INSTALL_ROOT/go"
    mkdir -p "$GO_INSTALL_ROOT"
    tar -C "$GO_INSTALL_ROOT" -xzf "$temp_dir/$tarball"
    rm -rf "$temp_dir"
}

ensure_go_for_caddy_build() {
    local install_command reply
    if go_is_available; then
        return 0
    fi

    echo -e "${YELLOW}Go ${REQUIRED_GO_MIN_VERSION}+ is required to build Caddy with $CADDY_GANDI_MODULE.${NC}"
    if ! install_command="$(describe_go_install_command)"; then
        echo -e "${RED}✗ No supported package manager found for automatic Go installation.${NC}"
        echo -e "${YELLOW}Install Go manually, or provision a wildcard certificate externally and configure Caddy to load cert files.${NC}"
        return 1
    fi

    echo -e "${BLUE}Suggested install command: $install_command${NC}"
    if is_truthy "$AUTO_INSTALL_PREREQS"; then
        echo -e "${BLUE}OPENMATES_CADDY_AUTO_INSTALL_PREREQS is enabled; installing Go now.${NC}"
    elif [ -t 0 ] || [ "${OPENMATES_CADDY_APPLY_TEST:-}" = "1" ]; then
        echo -e "${BLUE}Install Go now so Caddy can be rebuilt with $CADDY_GANDI_MODULE? [y/N]${NC}"
        read -r reply
        if ! is_truthy "$reply"; then
            echo -e "${RED}✗ Go installation declined.${NC}"
            echo -e "${YELLOW}Install Go manually, then rerun this script.${NC}"
            return 1
        fi
    else
        echo -e "${RED}✗ Cannot install Go from a non-interactive shell without explicit opt-in.${NC}"
        echo -e "${YELLOW}Rerun with OPENMATES_CADDY_AUTO_INSTALL_PREREQS=1, or install Go manually.${NC}"
        return 1
    fi

    run_go_install_command || {
        echo -e "${RED}✗ Failed to install Go using: $install_command${NC}"
        return 1
    }

    unset OPENMATES_CADDY_APPLY_TEST_GO_MISSING
    export PATH="$GO_INSTALL_ROOT/go/bin:$PATH"
    if ! go_is_available; then
        echo -e "${RED}✗ Go installation finished but Go ${REQUIRED_GO_MIN_VERSION}+ is still not available on PATH.${NC}"
        return 1
    fi
    echo -e "${GREEN}✓ Go is available for Caddy module build${NC}"
}

warn_if_gandi_token_not_in_shell() {
    if [ -n "${GANDI_BEARER_TOKEN:-}" ] || gandi_token_configured_for_service; then
        return 0
    fi

    echo -e "${YELLOW}⚠ Caddyfile requires Gandi DNS-01 but no existing Caddy service Gandi token was detected.${NC}"
    echo -e "${YELLOW}Check mode will use a dummy token for syntax only. Apply mode will request and store the real token.${NC}"
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
    local caddy_path temp_dir xcaddy_bin built_caddy backup_path
    caddy_path="$(command -v "$CADDY_BIN" || true)"
    if [ -z "$caddy_path" ]; then
        echo -e "${RED}✗ Cannot find Caddy binary '$CADDY_BIN'.${NC}"
        return 1
    fi

    ensure_go_for_caddy_build || return 1

    if ! echo "$REQUIRED_CADDY_VERSION" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+'; then
        echo -e "${RED}✗ Invalid required Caddy version '$REQUIRED_CADDY_VERSION'.${NC}"
        return 1
    fi

    temp_dir="$(mktemp -d /tmp/openmates-caddy-build.XXXXXX)"
    xcaddy_bin="$temp_dir/xcaddy"
    built_caddy="$temp_dir/caddy"
    echo -e "${BLUE}Installing xcaddy into temporary build directory...${NC}"
    PATH="$GO_INSTALL_ROOT/go/bin:$PATH" GOBIN="$temp_dir" GOTOOLCHAIN=local go install "$CADDY_XCADDY_PACKAGE"

    echo -e "${BLUE}Building Caddy $REQUIRED_CADDY_VERSION with $CADDY_GANDI_PACKAGE...${NC}"
    PATH="$GO_INSTALL_ROOT/go/bin:$PATH" GOTOOLCHAIN=local "$xcaddy_bin" build "$REQUIRED_CADDY_VERSION" --with "$CADDY_GANDI_PACKAGE" --output "$built_caddy"

    if ! "$built_caddy" list-modules 2>/dev/null | grep -qx "$CADDY_GANDI_MODULE"; then
        echo -e "${RED}✗ Built Caddy binary does not contain $CADDY_GANDI_MODULE.${NC}"
        return 1
    fi
    if ! "$built_caddy" build-info 2>/dev/null | grep -Eq "[[:space:]]github.com/caddy-dns/gandi[[:space:]]+${REQUIRED_CADDY_GANDI_VERSION//./\.}([[:space:]]|$)"; then
        echo -e "${RED}✗ Built Caddy binary does not contain github.com/caddy-dns/gandi $REQUIRED_CADDY_GANDI_VERSION.${NC}"
        return 1
    fi
    if ! "$built_caddy" build-info 2>/dev/null | grep -Eq "[[:space:]]github.com/libdns/gandi[[:space:]]+${REQUIRED_LIBDNS_GANDI_VERSION//./\.}([[:space:]]|$)"; then
        echo -e "${RED}✗ Built Caddy binary does not contain github.com/libdns/gandi $REQUIRED_LIBDNS_GANDI_VERSION.${NC}"
        return 1
    fi

    backup_path="${caddy_path}.openmates-backup-$(date +%Y%m%d%H%M%S)"
    echo -e "${BLUE}Installing custom Caddy binary to $caddy_path...${NC}"
    cp "$caddy_path" "$backup_path"
    chmod 755 "$backup_path"
    install -m 755 "$built_caddy" "$caddy_path"
    echo -e "${GREEN}✓ Installed Caddy $REQUIRED_CADDY_VERSION with $CADDY_GANDI_MODULE $REQUIRED_CADDY_GANDI_VERSION${NC}"
    echo -e "${GREEN}✓ Previous Caddy binary backed up at $backup_path${NC}"
}

gandi_token_configured_for_service() {
    if [ -f "$CADDY_SERVICE_ENV_FILE" ] && grep -Eq '^GANDI_BEARER_TOKEN=.+$' "$CADDY_SERVICE_ENV_FILE" 2>/dev/null; then
        return 0
    fi

    systemctl show caddy --property=Environment --value 2>/dev/null \
        | tr ' ' '\n' \
        | grep -Eq '^GANDI_BEARER_TOKEN=.+$'
}

validate_gandi_token_value() {
    local token="$1"
    if [ -z "$token" ]; then
        echo -e "${RED}✗ Empty Gandi token is not allowed.${NC}"
        return 1
    fi
    if [[ "$token" =~ [[:space:]] ]]; then
        echo -e "${RED}✗ Gandi token must not contain whitespace or newlines.${NC}"
        return 1
    fi
}

prompt_for_gandi_token() {
    local token
    if [ ! -t 0 ] && [ "${OPENMATES_CADDY_APPLY_TEST:-}" != "1" ]; then
        echo -e "${RED}✗ GANDI_BEARER_TOKEN is not configured for the Caddy service and this shell is non-interactive.${NC}"
        echo -e "${YELLOW}Run this script from an interactive root shell or pass GANDI_BEARER_TOKEN only for this setup run.${NC}"
        return 1
    fi

    echo -e "${BLUE}Enter the Gandi bearer token for Caddy DNS-01 (input hidden):${NC}"
    if [ -t 0 ]; then
        read -r -s token
        echo ""
    else
        read -r token
    fi
    validate_gandi_token_value "$token" || return 1
    GANDI_BEARER_TOKEN="$token"
}

write_gandi_token_for_service() {
    local token="$1" env_dir dropin_dir tmp_env tmp_dropin
    validate_gandi_token_value "$token" || return 1

    env_dir="$(dirname "$CADDY_SERVICE_ENV_FILE")"
    dropin_dir="$(dirname "$CADDY_SERVICE_DROPIN")"
    mkdir -p "$env_dir" "$dropin_dir"

    tmp_env="$(mktemp "$env_dir/openmates-gandi.env.XXXXXX")"
    printf 'GANDI_BEARER_TOKEN=%s\n' "$token" >"$tmp_env"
    chown root:root "$tmp_env"
    chmod 600 "$tmp_env"
    mv "$tmp_env" "$CADDY_SERVICE_ENV_FILE"

    tmp_dropin="$(mktemp "$dropin_dir/openmates-gandi-token.conf.XXXXXX")"
    printf '[Service]\nEnvironmentFile=%s\n' "$CADDY_SERVICE_ENV_FILE" >"$tmp_dropin"
    chown root:root "$tmp_dropin"
    chmod 644 "$tmp_dropin"
    mv "$tmp_dropin" "$CADDY_SERVICE_DROPIN"
    write_caddy_no_environ_dropin || return 1
    systemctl daemon-reload

    echo -e "${GREEN}✓ Stored Gandi token for the Caddy service at $CADDY_SERVICE_ENV_FILE${NC}"
    echo -e "${GREEN}✓ Installed systemd drop-in at $CADDY_SERVICE_DROPIN${NC}"
}

write_caddy_no_environ_dropin() {
    local dropin_dir tmp_dropin caddy_path
    caddy_path="$(command -v "$CADDY_BIN" || true)"
    if [ -z "$caddy_path" ]; then
        echo -e "${RED}✗ Cannot find Caddy binary '$CADDY_BIN' for systemd ExecStart override.${NC}"
        return 1
    fi

    dropin_dir="$(dirname "$CADDY_SERVICE_NO_ENVIRON_DROPIN")"
    mkdir -p "$dropin_dir"

    tmp_dropin="$(mktemp "$dropin_dir/openmates-no-environ.conf.XXXXXX")"
    printf '[Service]\nExecStart=\nExecStart=%s run --config %s\n' "$caddy_path" "$SYSTEM_CADDYFILE" >"$tmp_dropin"
    chown root:root "$tmp_dropin"
    chmod 644 "$tmp_dropin"
    mv "$tmp_dropin" "$CADDY_SERVICE_NO_ENVIRON_DROPIN"
    echo -e "${GREEN}✓ Installed systemd ExecStart override without --environ at $CADDY_SERVICE_NO_ENVIRON_DROPIN${NC}"
}

ensure_gandi_token_for_service() {
    if gandi_token_configured_for_service; then
        echo -e "${GREEN}✓ Caddy service already has a Gandi token configured${NC}"
        write_caddy_no_environ_dropin || return 1
        systemctl daemon-reload
        return 0
    fi

    if [ -z "${GANDI_BEARER_TOKEN:-}" ]; then
        prompt_for_gandi_token || return 1
    else
        validate_gandi_token_value "$GANDI_BEARER_TOKEN" || return 1
        echo -e "${BLUE}Using GANDI_BEARER_TOKEN from this shell for one-time Caddy service setup.${NC}"
    fi

    write_gandi_token_for_service "$GANDI_BEARER_TOKEN"
}

if [ "$SET_GANDI_TOKEN_ONLY" = true ]; then
    if [ -z "$GANDI_TOKEN_ARG" ]; then
        prompt_for_gandi_token || exit 1
        GANDI_TOKEN_ARG="$GANDI_BEARER_TOKEN"
    fi
    write_gandi_token_for_service "$GANDI_TOKEN_ARG" || exit 1
    echo -e "${GREEN}=== Gandi token stored; restart Caddy after revoking the old token ===${NC}"
    exit 0
fi

# Ensure Caddy can load DNS provider modules before adaptation. This is done
# before caddy adapt because Caddyfile adaptation fails if the module is missing
# or if the provider token placeholder expands to an empty value.
if config_requires_gandi_dns; then
    echo -e "${BLUE}Checking Caddy Gandi DNS provider support...${NC}"
    gandi_module_status="$(caddy_gandi_module_status)"
    if [ "$gandi_module_status" = "compatible" ]; then
        echo -e "${GREEN}✓ Caddy has $CADDY_GANDI_MODULE with compatible Gandi/libdns versions${NC}"
    elif [ "$CHECK_ONLY" = true ]; then
        if [ "$gandi_module_status" = "missing" ]; then
            echo -e "${RED}✗ Caddyfile requires $CADDY_GANDI_MODULE but the installed Caddy binary does not include it.${NC}"
        else
            echo -e "${RED}✗ Caddyfile requires $CADDY_GANDI_MODULE but the installed Caddy binary has stale Gandi/libdns module versions.${NC}"
        fi
        echo -e "${YELLOW}Run without --check as root to let this script build and install Caddy $REQUIRED_CADDY_VERSION with caddy-dns/gandi $REQUIRED_CADDY_GANDI_VERSION.${NC}"
        exit 1
    else
        if [ "$gandi_module_status" = "missing" ]; then
            echo -e "${YELLOW}Caddy is missing $CADDY_GANDI_MODULE; building and installing a compatible binary.${NC}"
        else
            echo -e "${YELLOW}Caddy has stale Gandi/libdns module versions; rebuilding a compatible binary.${NC}"
        fi
        install_caddy_with_gandi_module || exit 1
    fi

    if [ "$CHECK_ONLY" = true ]; then
        warn_if_gandi_token_not_in_shell
    else
        ensure_gandi_token_for_service || exit 1
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
