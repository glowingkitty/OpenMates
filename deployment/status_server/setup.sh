#!/bin/sh
# openmates-status-setup: install, configure and update the status server.
#
# Run as root on the separate status server (Debian). Setup and update are the
# same command:
#   1. first run: installs Docker, a firewall (22/80/443) and automatic
#      security updates
#   2. pulls the status image
#   3. writes status.env (mode 600):
#        --config-stdin   from standard input (the dev server pipes the values
#                         it read from Vault: scripts/status_server.py setup)
#        VAULT_ADDR set   read from Vault with VAULT_TOKEN / VAULT_TOKEN_FILE
#        otherwise        keeps the existing status.env (plain update)
#   4. installs the compose file from the image and (re)starts the server
#
# Optional settings in $STATUS_DIR/settings.env: STATUS_IMAGE, VAULT_ADDR,
# VAULT_TOKEN_FILE, VAULT_NETWORK, HTTP_PORT, HTTPS_PORT, GATUS_UI_PORT.
# No secrets or addresses are stored in this script or the image.
set -eu

STATUS_DIR="${STATUS_DIR:-/opt/openmates-status}"
SETUP_BIN="${SETUP_BIN:-/usr/local/bin/openmates-status-setup}"
CONFIG_STDIN=0
for arg in "$@"; do
  case "$arg" in
    --config-stdin) CONFIG_STDIN=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ -f "$STATUS_DIR/settings.env" ]; then
  set -a; . "$STATUS_DIR/settings.env"; set +a
fi
STATUS_IMAGE="${STATUS_IMAGE:-ghcr.io/glowingkitty/openmates-status:main}"

install_system() {
  [ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
  if ! command -v docker >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -q
    apt-get install -y -q docker.io docker-compose ufw unattended-upgrades
    ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
    systemctl enable --now docker unattended-upgrades
  fi
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose --project-directory "$STATUS_DIR" -f "$STATUS_DIR/docker-compose.yml" "$@"
  else
    docker-compose --project-directory "$STATUS_DIR" -f "$STATUS_DIR/docker-compose.yml" "$@"
  fi
}

[ "${OPENMATES_STATUS_SKIP_SYSTEM:-0}" = 1 ] || install_system
mkdir -p "$STATUS_DIR"
umask 077

echo "Pulling $STATUS_IMAGE"
case "$STATUS_IMAGE" in
  *:local) ;;  # dev tests use a locally built image
  *) docker pull -q "$STATUS_IMAGE" >/dev/null ;;
esac

if [ "$CONFIG_STDIN" = 1 ]; then
  cat > "$STATUS_DIR/status.env.new"
elif [ -n "${VAULT_ADDR:-}" ]; then
  if [ -z "${VAULT_TOKEN:-}" ] && [ -n "${VAULT_TOKEN_FILE:-}" ]; then
    VAULT_TOKEN="$(cat "$VAULT_TOKEN_FILE")"
  fi
  [ -n "${VAULT_TOKEN:-}" ] || { echo "VAULT_TOKEN or VAULT_TOKEN_FILE is required with VAULT_ADDR" >&2; exit 1; }
  export VAULT_ADDR VAULT_TOKEN
  docker run --rm --network "${VAULT_NETWORK:-host}" -e VAULT_ADDR -e VAULT_TOKEN "$STATUS_IMAGE" \
    python -m status_agent.vault_env > "$STATUS_DIR/status.env.new"
elif [ ! -s "$STATUS_DIR/status.env" ]; then
  echo "No status.env yet: run the setup from the dev server (scripts/status_server.py setup)" >&2
  echo "or set VAULT_ADDR and VAULT_TOKEN_FILE in $STATUS_DIR/settings.env." >&2
  exit 1
fi
if [ -f "$STATUS_DIR/status.env.new" ]; then
  grep -q '^GATUS_EXTERNAL_TOKEN=.' "$STATUS_DIR/status.env.new" || {
    rm -f "$STATUS_DIR/status.env.new"; echo "config is incomplete (no GATUS_EXTERNAL_TOKEN)" >&2; exit 1; }
  mv "$STATUS_DIR/status.env.new" "$STATUS_DIR/status.env"
fi

# Compose file and this script come from the image, so both match its version.
umask 022
docker run --rm --entrypoint cat "$STATUS_IMAGE" /app/deploy/docker-compose.yml > "$STATUS_DIR/docker-compose.yml"
docker run --rm --entrypoint cat "$STATUS_IMAGE" /app/deploy/setup.sh > "$SETUP_BIN.new"
chmod 755 "$SETUP_BIN.new" && mv "$SETUP_BIN.new" "$SETUP_BIN"
{
  echo "STATUS_IMAGE=$STATUS_IMAGE"
  echo "HTTP_PORT=${HTTP_PORT:-80}"
  echo "HTTPS_PORT=${HTTPS_PORT:-443}"
  echo "GATUS_UI_PORT=${GATUS_UI_PORT:-8080}"
} > "$STATUS_DIR/.env"

compose up -d --remove-orphans --force-recreate
case "$STATUS_IMAGE" in
  *:local) ;;
  *) docker image prune -f >/dev/null ;;
esac
compose ps
echo "Status server running ($STATUS_IMAGE)."
