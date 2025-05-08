import logging

# Import base service and mixins
from .cache_base import CacheServiceBase
from .cache_user_mixin import UserCacheMixin
from .cache_chat_mixin import ChatCacheMixin
from .cache_order_mixin import OrderCacheMixin
from .cache_legacy_mixin import LegacyChatCacheMixin

# Import schemas used by mixins (if any are directly type hinted in method signatures)
# For example, if ChatCacheMixin methods directly hint at CachedChatVersions, etc.
# from app.schemas.chat import CachedChatVersions, CachedChatListItemData # Already in ChatCacheMixin

logger = logging.getLogger(__name__)

class CacheService(
    CacheServiceBase,
    UserCacheMixin,
    ChatCacheMixin,
    OrderCacheMixin,
    LegacyChatCacheMixin
):
    """
    Service for caching data using Dragonfly (Redis-compatible).
    This class combines a base service with various mixins for modular functionality.
    """
    def __init__(self):
        # Initialize the base class which sets up the Redis connection and constants
        super().__init__()
        logger.info("CacheService fully initialized with all mixins.")

# Optional: Instantiate a global cache service instance if your application uses one.
# cache_service = CacheService()
# logger.info("Global CacheService instance created.")