# syntax=docker/dockerfile:1.7
# OpenMates Directus 11.5 runtime with the internal chat-recovery extension.
# The extension is baked into the image so empty host/named volumes cannot mask it.
# Startup fails unless Directus loads the endpoint and internal auth fails closed.
# Container health additionally requires the recovery collections and indexes.

FROM directus/directus:11.5

USER root
RUN apk add --no-cache curl postgresql-client

COPY --chown=node:node extensions /directus/extensions
RUN mkdir -p /directus/extensions/chat-recovery-transaction/dist \
    && cp /directus/extensions/chat-recovery-transaction/src/*.js \
        /directus/extensions/chat-recovery-transaction/dist/

COPY --chmod=755 <<'START_SCRIPT' /usr/local/bin/openmates-directus-start
#!/bin/sh
set -eu

: "${INTERNAL_API_SHARED_TOKEN:?INTERNAL_API_SHARED_TOKEN is required}"
test -r /directus/extensions/chat-recovery-transaction/package.json
test -r /directus/extensions/chat-recovery-transaction/dist/index.js

node cli.js bootstrap
pm2-runtime start ecosystem.config.cjs &
directus_pid=$!
trap 'kill -TERM "$directus_pid" 2>/dev/null || true' INT TERM

endpoint_status=""
attempt=0
while [ "$attempt" -lt 30 ]; do
  if ! kill -0 "$directus_pid" 2>/dev/null; then
    wait "$directus_pid"
    exit 1
  fi
  endpoint_status="$(curl --silent --show-error --output /tmp/chat-recovery-startup.json \
    --write-out '%{http_code}' --request POST \
    --header 'Content-Type: application/json' \
    --data '{"operation":"list_available_jobs","data":{"protocol_version":1,"hashed_user_id":"0000000000000000000000000000000000000000000000000000000000000000","device_hash":"startup-check"}}' \
    http://127.0.0.1:8055/chat-recovery-transaction/ || true)"
  # No internal token is intentionally supplied. A loaded, fail-closed endpoint returns 401.
  if [ "$endpoint_status" = "401" ]; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 2
done

if [ "$endpoint_status" != "401" ]; then
  echo "FATAL: chat-recovery-transaction endpoint failed startup verification (HTTP ${endpoint_status:-none})" >&2
  kill -TERM "$directus_pid" 2>/dev/null || true
  wait "$directus_pid" || true
  exit 1
fi

wait "$directus_pid"
START_SCRIPT

COPY --chmod=755 <<'HEALTH_SCRIPT' /usr/local/bin/openmates-directus-health
#!/bin/sh
set -eu

: "${INTERNAL_API_SHARED_TOKEN:?INTERNAL_API_SHARED_TOKEN is required}"
: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_DATABASE:?DB_DATABASE is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"

curl --fail --silent --show-error --output /tmp/chat-recovery-health.json \
  --request POST \
  --header 'Content-Type: application/json' \
  --header "X-Internal-Service-Token: ${INTERNAL_API_SHARED_TOKEN}" \
  --data '{"operation":"list_available_jobs","data":{"protocol_version":1,"hashed_user_id":"0000000000000000000000000000000000000000000000000000000000000000","device_hash":"health-check"}}' \
  http://127.0.0.1:8055/chat-recovery-transaction/

index_count="$(PGCONNECT_TIMEOUT=5 PGPASSWORD="$DB_PASSWORD" psql \
  --host "$DB_HOST" --port "$DB_PORT" --username "$DB_USER" --dbname "$DB_DATABASE" \
  --tuples-only --no-align --command "
    SELECT count(*)
    FROM pg_indexes
    WHERE schemaname = 'public'
      AND indexname IN (
        'chat_turn_preflights_owner_chat_turn_uq',
        'chat_turn_preflights_user_message_uq',
        'chat_turn_preflights_task_uq',
        'chat_turn_preflights_billing_uq',
        'chat_inference_outbox_preflight_uq',
        'chat_inference_outbox_task_uq',
        'chat_inference_outbox_billing_uq',
        'chat_recovery_jobs_owner_chat_turn_uq',
        'chat_recovery_jobs_preflight_uq',
        'chat_recovery_jobs_task_uq',
        'chat_recovery_jobs_assistant_message_uq'
      );")"
test "$index_count" = "11"
HEALTH_SCRIPT

USER node
CMD ["/usr/local/bin/openmates-directus-start"]
HEALTHCHECK --interval=10s --timeout=8s --start-period=60s --retries=12 CMD ["/usr/local/bin/openmates-directus-health"]
