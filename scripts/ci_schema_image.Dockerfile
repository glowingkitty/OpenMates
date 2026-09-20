FROM postgres:13-alpine

COPY test-results/ci-private/openmates-ci-schema.sql.gz \
    /docker-entrypoint-initdb.d/20-openmates-schema.sql.gz
