# Default TTL values (in seconds)
DEFAULT_TTL = 3600  # 1 hour
USER_TTL = 86400    # 24 hours
SESSION_TTL = 86400 # 24 hours

# Cache key prefixes - Existing
USER_KEY_PREFIX = "user_profile:"
SESSION_KEY_PREFIX = "session:"
USER_DEVICE_KEY_PREFIX = "user_device:"
USER_DEVICE_LIST_KEY_PREFIX = "user_device_list:"
ORDER_KEY_PREFIX = "order_status:"

# Obsolete/Legacy chat prefixes
CHAT_LIST_META_KEY_PREFIX = "chat_list_meta:"
USER_ACTIVE_CHATS_LRU_PREFIX = "user_active_chats_lru:"
USER_CHATS_SET_PREFIX = "user_chats:"

# TTLs for existing structures
CHAT_LIST_TTL = 3600 # 1 hour (For CHAT_LIST_META_KEY_PREFIX)
CHAT_METADATA_TTL = 1800  # 30 minutes (For old chat:{chat_id}:metadata key)
USER_CHATS_SET_TTL = 86400 # 24 hours (For USER_CHATS_SET_PREFIX)
DRAFT_TTL = 1800  # 30 minutes (Likely obsolete)

# --- New Chat Sync Architecture Cache Settings ---
# TTLs for new structures
CHAT_IDS_VERSIONS_TTL = 86400  # 24 hours
CHAT_VERSIONS_TTL = 2700       # 45 minutes
CHAT_LIST_ITEM_DATA_TTL = 2700 # 45 minutes
CHAT_MESSAGES_TTL = 3600       # 1 hour
TOP_N_MESSAGES_COUNT = 3       # Configurable: How many chats keep full messages in cache