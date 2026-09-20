FROM postgres:13-alpine

COPY --chmod=0444 openmates-ci-schema.sql.gz /docker-entrypoint-initdb.d/20-openmates-schema.sql.gz
