# Status agent: standard library only, no pip dependencies.
FROM python:3.12.16-alpine
RUN adduser -D -u 10001 agent && mkdir -p /var/lib/status-agent /srv/data \
    && chown agent /var/lib/status-agent /srv/data
COPY status_agent /app/status_agent
WORKDIR /app
USER agent
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "status_agent.main"]
