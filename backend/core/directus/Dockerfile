# syntax=docker/dockerfile:1.7
# OpenMates Directus 11.5 runtime with the internal chat-recovery extension.
# The extension is baked into the image so empty host/named volumes cannot mask it.
# Startup fails unless Directus loads the endpoint and internal auth fails closed.
# Container health additionally requires the recovery collections and indexes.

FROM directus/directus:11.5

USER root
RUN apk add --no-cache curl postgresql-client su-exec

COPY --chown=node:node extensions /directus/extensions
RUN mkdir -p /directus/extensions/chat-recovery-transaction/dist \
    && cp /directus/extensions/chat-recovery-transaction/src/*.js \
        /directus/extensions/chat-recovery-transaction/dist/ \
    && mkdir -p /directus/extensions/workflow-runtime-transaction/dist \
    && cp /directus/extensions/workflow-runtime-transaction/src/*.js \
        /directus/extensions/workflow-runtime-transaction/dist/ \
    && mkdir -p /directus/extensions/sub-chat-orchestration-transaction/dist \
    && cp /directus/extensions/sub-chat-orchestration-transaction/src/*.js \
        /directus/extensions/sub-chat-orchestration-transaction/dist/ \
    && mkdir -p /directus/extensions/anonymous-usage-transaction/dist \
    && cp /directus/extensions/anonymous-usage-transaction/src/*.js \
        /directus/extensions/anonymous-usage-transaction/dist/

COPY --chmod=755 <<'START_SCRIPT' /usr/local/bin/openmates-directus-start
#!/bin/sh
set -eu

: "${INTERNAL_API_SHARED_TOKEN:?INTERNAL_API_SHARED_TOKEN is required}"
test -r /directus/extensions/chat-recovery-transaction/package.json
test -r /directus/extensions/chat-recovery-transaction/dist/index.js
test -r /directus/extensions/workflow-runtime-transaction/package.json
test -r /directus/extensions/workflow-runtime-transaction/dist/index.js
test -r /directus/extensions/sub-chat-orchestration-transaction/package.json
test -r /directus/extensions/sub-chat-orchestration-transaction/dist/index.js
test -r /directus/extensions/anonymous-usage-transaction/package.json
test -r /directus/extensions/anonymous-usage-transaction/dist/index.js

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

endpoint_status=""
attempt=0
while [ "$attempt" -lt 30 ]; do
  endpoint_status="$(curl --silent --show-error --output /tmp/anonymous-usage-startup.json \
    --write-out '%{http_code}' --request POST \
    --header 'Content-Type: application/json' \
    --data '{"operation":"health_check","data":{"protocol_version":1}}' \
    http://127.0.0.1:8055/anonymous-usage-transaction/ || true)"
  if [ "$endpoint_status" = "401" ]; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 2
done
if [ "$endpoint_status" != "401" ]; then
  echo "FATAL: anonymous-usage-transaction endpoint failed startup verification (HTTP ${endpoint_status:-none})" >&2
  kill -TERM "$directus_pid" 2>/dev/null || true
  wait "$directus_pid" || true
  exit 1
fi

endpoint_status=""
attempt=0
while [ "$attempt" -lt 30 ]; do
  endpoint_status="$(curl --silent --show-error --output /tmp/sub-chat-orchestration-startup.json \
    --write-out '%{http_code}' --request POST \
    --header 'Content-Type: application/json' \
    --data '{"operation":"health_check","data":{"protocol_version":1}}' \
    http://127.0.0.1:8055/sub-chat-orchestration-transaction/ || true)"
  if [ "$endpoint_status" = "401" ]; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 2
done
if [ "$endpoint_status" != "401" ]; then
  echo "FATAL: sub-chat-orchestration-transaction endpoint failed startup verification (HTTP ${endpoint_status:-none})" >&2
  kill -TERM "$directus_pid" 2>/dev/null || true
  wait "$directus_pid" || true
  exit 1
fi

endpoint_status=""
attempt=0
while [ "$attempt" -lt 30 ]; do
  endpoint_status="$(curl --silent --show-error --output /tmp/workflow-runtime-startup.json \
    --write-out '%{http_code}' --request POST \
    --header 'Content-Type: application/json' \
    --data '{"operation":"health_check","data":{"protocol_version":1}}' \
    http://127.0.0.1:8055/workflow-runtime-transaction/ || true)"
  if [ "$endpoint_status" = "401" ]; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 2
done
if [ "$endpoint_status" != "401" ]; then
  echo "FATAL: workflow-runtime-transaction endpoint failed startup verification (HTTP ${endpoint_status:-none})" >&2
  kill -TERM "$directus_pid" 2>/dev/null || true
  wait "$directus_pid" || true
  exit 1
fi

wait "$directus_pid"
START_SCRIPT

COPY --chmod=755 <<'ENTRYPOINT_SCRIPT' /usr/local/bin/openmates-directus-entrypoint
#!/bin/sh
set -eu

mkdir -p /directus/uploads
chown node:node /directus/uploads
exec su-exec node:node /usr/local/bin/openmates-directus-start
ENTRYPOINT_SCRIPT

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

curl --fail --silent --show-error --output /tmp/workflow-runtime-health.json \
  --request POST \
  --header 'Content-Type: application/json' \
  --header "X-Internal-Service-Token: ${INTERNAL_API_SHARED_TOKEN}" \
  --data '{"operation":"health_check","data":{"protocol_version":1}}' \
  http://127.0.0.1:8055/workflow-runtime-transaction/

curl --fail --silent --show-error --output /tmp/sub-chat-orchestration-health.json \
  --request POST \
  --header 'Content-Type: application/json' \
  --header "X-Internal-Service-Token: ${INTERNAL_API_SHARED_TOKEN}" \
  --data '{"operation":"health_check","data":{"protocol_version":1}}' \
  http://127.0.0.1:8055/sub-chat-orchestration-transaction/

curl --fail --silent --show-error --output /tmp/anonymous-usage-health.json \
  --request POST \
  --header 'Content-Type: application/json' \
  --header "X-Internal-Service-Token: ${INTERNAL_API_SHARED_TOKEN}" \
  --data '{"operation":"health_check","data":{"protocol_version":1}}' \
  http://127.0.0.1:8055/anonymous-usage-transaction/

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

workflow_index_count="$(PGCONNECT_TIMEOUT=5 PGPASSWORD="$DB_PASSWORD" psql \
  --host "$DB_HOST" --port "$DB_PORT" --username "$DB_USER" --dbname "$DB_DATABASE" \
  --tuples-only --no-align --command "
    SELECT count(*)
    FROM pg_indexes
    WHERE schemaname = 'public'
      AND indexname IN (
        'workflow_triggers_due_claim_idx',
        'workflow_triggers_due_owner_idx',
        'workflow_runs_acceptance_identity_uq',
        'workflow_event_receipts_trigger_event_uq',
        'workflow_template_projections_workflow_uq'
      );")"
test "$workflow_index_count" = "5"

sub_chat_index_count="$(PGCONNECT_TIMEOUT=5 PGPASSWORD="$DB_PASSWORD" psql \
  --host "$DB_HOST" --port "$DB_PORT" --username "$DB_USER" --dbname "$DB_DATABASE" \
  --tuples-only --no-align --command "
    SELECT count(*)
    FROM pg_indexes
    WHERE schemaname = 'public'
      AND indexname IN (
        'sub_chat_orchestrations_owner_root_turn_uq',
        'sub_chat_orchestrations_owner_status_idx',
        'sub_chat_children_chat_uq',
        'sub_chat_children_orchestration_token_uq',
        'sub_chat_children_inference_task_uq',
        'sub_chat_children_orchestration_state_idx',
        'sub_chat_batches_orchestration_parent_id_uq',
        'sub_chat_batches_orchestration_claim_idx',
        'sub_chat_operations_identity_uq',
        'sub_chat_operations_orchestration_state_idx',
        'sub_chat_operations_charge_idx',
        'usage_charge_id_uq',
        'usage_user_root_created_idx',
        'usage_orchestration_created_idx',
        'billing_charge_identities_charge_uq',
        'billing_charge_identities_user_created_idx',
        'billing_refund_identities_refund_uq',
        'billing_settlement_outbox_due_idx',
        'team_credit_events_event_uq',
        'team_usage_events_event_uq'
      );")"
test "$sub_chat_index_count" = "20"
HEALTH_SCRIPT

USER root
CMD ["/usr/local/bin/openmates-directus-entrypoint"]
HEALTHCHECK --interval=10s --timeout=8s --start-period=10m --retries=12 CMD ["su-exec", "node:node", "/usr/local/bin/openmates-directus-health"]
