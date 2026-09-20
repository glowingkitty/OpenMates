FROM postgres:13-alpine

COPY openmates-ci-schema.sql.gz /docker-entrypoint-initdb.d/20-openmates-schema.sql.gz
