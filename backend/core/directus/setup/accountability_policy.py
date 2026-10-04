"""Reviewed Directus collection accountability overrides.

The application stores chat history, embed versions, and test results in its own
collections. Generic Directus snapshots duplicate those records and are not read
by the product. Keep this list deliberately small: an override in a schema must
be reviewed here before schema setup applies it to an existing collection.
"""

REDUCED_ACCOUNTABILITY = {
    "chats": None,
    "messages": None,
    "embeds": None,
    "test_results": None,
    "chat_message_archive_segments": None,
    "chat_message_archive_pages": None,
    "embed_diffs": None,
    "chat_recovery_outputs": None,
    "chat_recovery_account_fences": None,
    "chat_recovery_chat_deletion_fences": None,
    "chat_recovery_output_producers": None,
    "chat_recovery_output_producer_children": None,
    "chat_recovery_authorized_rerenders": None,
    "chat_recovery_authorized_direct_skills": None,
    "chat_recovery_legacy_output_producers": None,
    "chat_recovery_legacy_batch_claims": None,
    "chat_compression_checkpoints": None,
}


def configured_accountability(collection_name: str, collection: dict) -> tuple[bool, str | None]:
    """Return whether an explicit, reviewed override is present and its value."""
    meta = collection.get("meta") or {}
    if "accountability" not in meta:
        return False, None
    value = meta["accountability"]
    if collection_name not in REDUCED_ACCOUNTABILITY or value != REDUCED_ACCOUNTABILITY[collection_name]:
        raise ValueError(f"Unreviewed Directus accountability override for {collection_name}")
    return True, value
