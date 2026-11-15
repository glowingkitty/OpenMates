# status.openmates.org: one image with Gatus (checks), Caddy (TLS and the
# public page) and the status agent (probes, alerts, status.json).
# Built and published by .github/workflows/publish-status-image.yml.
# It holds no secrets or server addresses: setup.sh writes them from Vault into
# the server's env file at deploy time.

FROM twinproduction/gatus:v5.38.0 AS gatus
FROM caddy:2.11.7-alpine AS caddy

FROM python:3.12.16-alpine
RUN apk add --no-cache ca-certificates libcap \
    && adduser -D -u 10001 status \
    && mkdir -p /var/lib/openmates-status \
    && chown status /var/lib/openmates-status
COPY --from=gatus /gatus /usr/local/bin/gatus
COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy
# Caddy listens on 80/443 without running as root.
RUN setcap cap_net_bind_service=+ep /usr/local/bin/caddy && apk del libcap
COPY agent/status_agent /app/status_agent
COPY gatus/config.yaml /app/gatus/config.yaml
COPY Caddyfile /app/Caddyfile
COPY site /app/site
COPY docker-compose.yml setup.sh /app/deploy/
WORKDIR /app
USER status
ENV PYTHONUNBUFFERED=1 \
    GATUS_CONFIG_PATH=/app/gatus/config.yaml \
    GATUS_URL=http://127.0.0.1:8080 \
    STATE_DIR=/var/lib/openmates-status/agent \
    PUBLIC_DATA_DIR=/var/lib/openmates-status/public \
    XDG_DATA_HOME=/var/lib/openmates-status/caddy-data \
    XDG_CONFIG_HOME=/var/lib/openmates-status/caddy-config
EXPOSE 80 443 8080
CMD ["python", "-m", "status_agent.supervise"]
