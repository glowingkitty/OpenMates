// Bundled runtime data; no TypeScript application execution.

pub(super) const MINIMAL_ENV_TEMPLATE: &str = r###"# OpenMates self-host image-mode environment
SECRET__MISTRAL_AI__API_KEY=
SECRET__CEREBRAS__API_KEY=
SECRET__GROQ__API_KEY=
SECRET__OPENAI__API_KEY=
SECRET__ANTHROPIC__API_KEY=
SECRET__GOOGLE_AI_STUDIO__API_KEY=
SECRET__TYPESAFE__API_KEY=
SECRET__OPENROUTER__API_KEY=
SECRET__TOGETHER__API_KEY=
SECRET__BRAVE__API_KEY=
SECRET__FIRECRAWL__API_KEY=
SECRET__CONTEXT7__API_KEY=
DATABASE_ADMIN_EMAIL=admin@example.com
DATABASE_ADMIN_PASSWORD=
DATABASE_NAME=directus
DATABASE_USERNAME=directus
DATABASE_PASSWORD=
DIRECTUS_TOKEN=
DIRECTUS_SECRET=
DRAGONFLY_PASSWORD=
OPENOBSERVE_ROOT_EMAIL=admin@openmates.internal
OPENOBSERVE_ROOT_PASSWORD=
INTERNAL_API_SHARED_TOKEN=
TUNNEL_TRIGGER_SECRET=<PLACEHOLDER>
SERVER_ENVIRONMENT=production
FRONTEND_URLS="http://localhost:5173"
PRODUCTION_URL="http://localhost:5173"
TRUSTED_PROXY_IPS="172.16.0.0/12"
CORE_SIDECAR_URL=http://admin-sidecar:8001
CLEAR_CACHE_ON_UPDATE=true
SIGNUP_LIMIT=20
SELF_HOST_SIGNUP_MODE=invite_only
SELF_HOST_SIGNUP_ALLOWED_DOMAINS=
SELF_HOST_FIRST_INVITE_CODE=
APPLICATION_PREVIEW_ORIGIN=
PROD_CORE_API_URL=
PROD_INTERNAL_API_SHARED_TOKEN=
DEV_CORE_API_URL=
DEV_INTERNAL_API_SHARED_TOKEN=
PREVIEW_CORS_ORIGINS=https://openmates.org
PREVIEW_ALLOWED_REFERERS=https://openmates.org/*
OPENMATES_IMAGE_REGISTRY=ghcr.io/glowingkitty
OPENMATES_IMAGE_TAG=
OPENMATES_CLOUD_OVERLAY_ENABLED=false
GIT_WORK_DIR=
DOCKER_GID=999
CELERY_AUTOSCALE_MAX=3
CELERY_AUTOSCALE_MIN=1
TASK_WORKER_CONCURRENCY=3
APP_AI_WORKER_CONCURRENCY=3
APP_IMAGES_WORKER_CONCURRENCY=3
APP_MUSIC_WORKER_CONCURRENCY=2
TASK_WORKER_MEMORY_LIMIT=3g
APP_AI_WORKER_MEMORY_LIMIT=2g
APP_IMAGES_WORKER_MEMORY_LIMIT=1792m
APP_MUSIC_WORKER_MEMORY_LIMIT=1536m
APP_VIDEOS_WORKER_MEMORY_LIMIT=1280m
APP_PDF_WORKER_MEMORY_LIMIT=1536m
APP_DOCS_WORKER_MEMORY_LIMIT=1536m
APP_CODE_WORKER_MEMORY_LIMIT=1g
APP_SOCIAL_MEDIA_WORKER_MEMORY_LIMIT=1536m
"###;

pub(super) const VAULT_CONFIG_TEMPLATE: &str = r###"# Minimal Vault configuration
listener "tcp" {
  address = "0.0.0.0:8200"
  tls_disable = true
}

storage "file" {
  path = "/vault/file"
}

api_addr = "http://0.0.0.0:8200"
ui = false
disable_mlock = true
log_level = "info"
"###;

pub(super) const SELFHOST_PROMTAIL_CONFIG_TEMPLATE: &str = r###"server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://openobserve:5080/api/default/loki/api/v1/push
    basic_auth:
      username: "${OPENOBSERVE_ROOT_EMAIL}"
      password: "${OPENOBSERVE_ROOT_PASSWORD}"

scrape_configs:
  - job_name: api-logs
    static_configs:
      - targets:
          - localhost
        labels:
          job: api-logs
          service: api
          container: api
          compose_project: openmates-core
          __path__: /var/log/api/api.log
    pipeline_stages:
      - drop:
          expression: '^\s*$'
      - json:
          expressions:
            level: level
            message: message
            name: name
            event_type: event_type
            status: status
          ignore_parse_errors: true
      - labels:
          level:
          name:
          event_type:
          status:

  - job_name: container-logs
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 30s
    relabel_configs:
      - source_labels: ["__meta_docker_container_name"]
        regex: "/(.*)"
        target_label: "container"
      - source_labels: ["__meta_docker_container_log_stream"]
        target_label: "logstream"
      - source_labels: ["__meta_docker_container_label_com_docker_compose_service"]
        target_label: "service"
      - source_labels: ["__meta_docker_container_label_com_docker_compose_project"]
        target_label: "compose_project"
    pipeline_stages:
      - drop:
          expression: '^\s*$'
      - json:
          expressions:
            json_level: level
          ignore_parse_errors: true
      - template:
          source: log_level
          template: "{{ if .json_level }}{{ .json_level }}{{ else }}info{{ end }}"
      - labels:
          level: log_level
"###;
