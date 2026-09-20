FROM postgres:13-alpine@sha256:fb9065b6e3e213bdc07edd372a5b2a26245840b7fb65d1fd8b6700106d51805c

LABEL org.openmates.ci.schema-bundle-format="openmates-postgres-plain-gzip-v2" \
      org.openmates.ci.schema-restore-semantics="fresh-volume-directus-credential-rotation-v2"

COPY --chmod=0444 openmates-ci-schema.sql.gz /docker-entrypoint-initdb.d/20-openmates-schema.sql.gz
COPY --chmod=0444 openmates-ci-schema-manifest.json /usr/local/share/openmates/schema-manifest.json
