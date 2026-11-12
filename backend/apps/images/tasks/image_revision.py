"""A change to a generated image of the same chat becomes the next version of that image.

Specification: feature.app-skill.images-generate (images-generate.revision.*).
Plan: docs/plans/image-edit-as-embed-version (Lane A). Wire contract for the
clients: docs/plans/image-edit-as-embed-version/wire-contract.md.

The mechanism is shared with videos.generate and lives in
``backend/shared/python_utils/media_revision.py``; this module binds it to the
``generated_image`` child (its defaults are the image kind), so the images
tasks and tests keep their names. Uploaded images, images of another chat and
every other case keep today's behaviour (a new image).
"""

from __future__ import annotations

from backend.shared.python_utils.media_revision import (
    IMAGE_KIND,
    REVISIONS_ENV,
    S3_KEYS_CACHE_TTL_SECONDS,
    RevisionNotSupported,
    RevisionPreconditionFailed,
    RevisionTarget,
    assert_current_version,
    billing_event_id,
    cache_file_keys,
    change_identity,
    find_revision_target,
    finish_published_revision,
    forget_cached_reference,
    history_row_exists,
    pinned_pointer,
    producer_outputs,
    publish_revision,
    refund_refused_revision,
    revision_content_fields,
    revision_note,
    revision_result_fields,
    revisions_enabled,
    run_with_batch_claims,
    union_file_keys,
    version_history_rows,
)

GENERATED_IMAGE_SOURCE = IMAGE_KIND.upload_source
APP_ID = IMAGE_KIND.app_id
CHILD_TYPE = IMAGE_KIND.child_type

__all__ = [
    "APP_ID", "CHILD_TYPE", "GENERATED_IMAGE_SOURCE", "REVISIONS_ENV", "S3_KEYS_CACHE_TTL_SECONDS",
    "RevisionNotSupported", "RevisionPreconditionFailed", "RevisionTarget", "assert_current_version",
    "billing_event_id", "cache_file_keys", "change_identity", "find_revision_target", "finish_published_revision",
    "forget_cached_reference", "history_row_exists", "pinned_pointer", "producer_outputs", "publish_revision",
    "refund_refused_revision", "revision_content_fields", "revision_note", "revision_result_fields",
    "revisions_enabled", "run_with_batch_claims", "union_file_keys", "version_history_rows",
]
