import logging
import os # Import os for environment variables
from typing import Optional, Dict, Any
import asyncio # Keep asyncio import if initialize_services uses it

from celery import Task # Import Task for context

# Import necessary services and utilities
from backend.core.api.app.services.cache import CacheService # Added for CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.services.pdf.invoice import InvoiceTemplateService
from backend.core.api.app.services.pdf.credit_note import CreditNoteTemplateService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.services.translations import TranslationService
from backend.core.api.app.services.invoiceninja.invoiceninja import InvoiceNinjaService # Import InvoiceNinjaService
from backend.core.api.app.services.payment.payment_service import PaymentService # Import PaymentService

logger = logging.getLogger(__name__)

# --- Base Task Class for Service Initialization ---
# This helps avoid initializing services multiple times if the task retries
class BaseServiceTask(Task):
    _directus_service: Optional[DirectusService] = None
    _encryption_service: Optional[EncryptionService] = None
    _s3_service: Optional[S3UploadService] = None
    _invoice_template_service: Optional[InvoiceTemplateService] = None
    _credit_note_template_service: Optional[CreditNoteTemplateService] = None
    _email_template_service: Optional[EmailTemplateService] = None
    _secrets_manager: Optional[SecretsManager] = None
    _translation_service: Optional[TranslationService] = None
    _invoice_ninja_service: Optional[InvoiceNinjaService] = None # Add InvoiceNinjaService attribute
    _cache_service: Optional[CacheService] = None # Added CacheService
    _payment_service: Optional[PaymentService] = None # Add PaymentService attribute

    async def initialize_services(self):
        # Determine if in development environment
        is_dev = os.getenv("SERVER_ENVIRONMENT", "development").lower() == "development"
        is_production = not is_dev # is_production is true if not development

        # Initialize SecretsManager first as others depend on it
        if self._secrets_manager is None:
            logger.debug(f"Initializing SecretsManager for task {self.request.id}")
            self._secrets_manager = SecretsManager()
            await self._secrets_manager.initialize()
            logger.debug(f"SecretsManager initialized for task {self.request.id}")
        else:
             logger.debug(f"SecretsManager already initialized for task {self.request.id}")

        # Initialize CacheService (does not depend on SecretsManager for its own init)
        if self._cache_service is None:
            logger.debug(f"Initializing CacheService for task {self.request.id}")
            self._cache_service = CacheService()
            # CacheService itself does not have an async initialize() method
            logger.debug(f"CacheService initialized for task {self.request.id}")
        else:
            logger.debug(f"CacheService already initialized for task {self.request.id}")

        # Initialize other services, passing the initialized SecretsManager
        # For EncryptionService and DirectusService, we use their default constructors
        # as per current BaseServiceTask pattern, not passing cache/encryption to them here.
        # If they internally need and cannot get cache/encryption, that's a deeper issue in those services
        # or this BaseServiceTask's init strategy for them.
        if self._directus_service is None:
            logger.debug(f"Initializing DirectusService for task {self.request.id}")
            self._directus_service = DirectusService(cache_service=self._cache_service, encryption_service=self._encryption_service) # Pass dependencies
            # DirectusService might not need async init, depends on its implementation
            logger.debug(f"DirectusService initialized for task {self.request.id}")
        else:
             logger.debug(f"DirectusService already initialized for task {self.request.id}")

        if self._encryption_service is None:
            logger.debug(f"Initializing EncryptionService for task {self.request.id}")
            # Assuming EncryptionService doesn't need secrets_manager for init
            self._encryption_service = EncryptionService(cache_service=self._cache_service) # Pass cache_service
            if hasattr(self._encryption_service, 'initialize') and asyncio.iscoroutinefunction(self._encryption_service.initialize):
                await self._encryption_service.initialize()
            logger.debug(f"EncryptionService initialized for task {self.request.id}")
        else:
             logger.debug(f"EncryptionService already initialized for task {self.request.id}")

        if self._s3_service is None:
            logger.debug(f"Initializing S3Service for task {self.request.id}")
            self._s3_service = S3UploadService(secrets_manager=self._secrets_manager)
            await self._s3_service.initialize() # S3 service needs init
            logger.debug(f"S3Service initialized for task {self.request.id}")
        else:
             logger.debug(f"S3Service already initialized for task {self.request.id}")

        if self._invoice_template_service is None:
            logger.debug(f"Initializing InvoiceTemplateService for task {self.request.id}")
            self._invoice_template_service = InvoiceTemplateService(secrets_manager=self._secrets_manager) # Pass SecretsManager
            logger.debug(f"InvoiceTemplateService initialized for task {self.request.id}")
        else:
             logger.debug(f"InvoiceTemplateService already initialized for task {self.request.id}")

        if self._credit_note_template_service is None:
            logger.debug(f"Initializing CreditNoteTemplateService for task {self.request.id}")
            self._credit_note_template_service = CreditNoteTemplateService(secrets_manager=self._secrets_manager) # Pass SecretsManager
            logger.debug(f"CreditNoteTemplateService initialized for task {self.request.id}")
        else:
             logger.debug(f"CreditNoteTemplateService already initialized for task {self.request.id}")

        if self._email_template_service is None:
            logger.debug(f"Initializing EmailTemplateService for task {self.request.id}")
            self._email_template_service = EmailTemplateService(secrets_manager=self._secrets_manager) # Pass SecretsManager
            # EmailTemplateService might not need async init, depends on its implementation
            logger.debug(f"EmailTemplateService initialized for task {self.request.id}")
        else:
             logger.debug(f"EmailTemplateService already initialized for task {self.request.id}")

        if self._translation_service is None:
            logger.debug(f"Initializing TranslationService for task {self.request.id}")
            self._translation_service = TranslationService()
            # TranslationService might not need async init, depends on its implementation
            logger.debug(f"TranslationService initialized for task {self.request.id}")

        # Initialize InvoiceNinjaService
        if self._invoice_ninja_service is None:
            logger.debug(f"Initializing InvoiceNinjaService for task {self.request.id}")
            # InvoiceNinjaService needs SecretsManager for async init
            self._invoice_ninja_service = await InvoiceNinjaService.create(secrets_manager=self._secrets_manager)
            logger.debug(f"InvoiceNinjaService initialized for task {self.request.id}")
        else:
             logger.debug(f"InvoiceNinjaService already initialized for task {self.request.id}")

        # Initialize PaymentService
        if self._payment_service is None:
            logger.debug(f"Initializing PaymentService for task {self.request.id}")
            self._payment_service = PaymentService(secrets_manager=self._secrets_manager)
            # PaymentService also needs to initialize its internal provider
            await self._payment_service.initialize(is_production=is_production) # Use is_production
            logger.debug(f"PaymentService initialized for task {self.request.id}")
        else:
            logger.debug(f"PaymentService already initialized for task {self.request.id}")


    async def publish_websocket_event(self, user_id_hash: str, event: str, payload: Dict[str, Any]):
        """
        Publish a WebSocket event to a user via Redis.
        """
        if self._cache_service is None:
            await self.initialize_services()
            
        client = await self._cache_service.client
        if client:
            import json as json_lib
            channel_key = f"websocket:user:{user_id_hash}"
            event_payload = {
                "event": event,
                "type": event,
                "event_for_client": event,
                "payload": payload
            }
            await client.publish(channel_key, json_lib.dumps(event_payload))
            logger.info(f"Published WebSocket event '{event}' to user '{user_id_hash[:8]}...'")
            return True
        else:
            logger.warning(f"Redis client not available, cannot publish WebSocket event '{event}'")
            return False


    @property
    def directus_service(self) -> DirectusService:
        if self._directus_service is None:
            # Log error before raising
            logger.error(f"DirectusService accessed before initialization in task {self.request.id}")
            raise RuntimeError("DirectusService not initialized. Call initialize_services first.")
        return self._directus_service

    @property
    def encryption_service(self) -> EncryptionService:
        if self._encryption_service is None:
             # Log error before raising
            logger.error(f"EncryptionService accessed before initialization in task {self.request.id}")
            raise RuntimeError("EncryptionService not initialized. Call initialize_services first.")
        return self._encryption_service

    @property
    def s3_service(self) -> S3UploadService:
        if self._s3_service is None:
             # Log error before raising
            logger.error(f"S3Service accessed before initialization in task {self.request.id}")
            raise RuntimeError("S3Service not initialized. Call initialize_services first.")
        return self._s3_service

    @property
    def invoice_template_service(self) -> InvoiceTemplateService:
        if self._invoice_template_service is None:
             # Log error before raising
            logger.error(f"InvoiceTemplateService accessed before initialization in task {self.request.id}")
            raise RuntimeError("InvoiceTemplateService not initialized. Call initialize_services first.")
        return self._invoice_template_service

    @property
    def credit_note_template_service(self) -> CreditNoteTemplateService:
        if self._credit_note_template_service is None:
             # Log error before raising
            logger.error(f"CreditNoteTemplateService accessed before initialization in task {self.request.id}")
            raise RuntimeError("CreditNoteTemplateService not initialized. Call initialize_services first.")
        return self._credit_note_template_service

    @property
    def email_template_service(self) -> EmailTemplateService:
        if self._email_template_service is None:
             # Log error before raising
            logger.error(f"EmailTemplateService accessed before initialization in task {self.request.id}")
            raise RuntimeError("EmailTemplateService not initialized. Call initialize_services first.")
        return self._email_template_service

    @property
    def secrets_manager(self) -> SecretsManager:
        if self._secrets_manager is None:
             # Log error before raising
            logger.error(f"SecretsManager accessed before initialization in task {self.request.id}")
            raise RuntimeError("SecretsManager not initialized. Call initialize_services first.")
        return self._secrets_manager
    
    @property
    def translation_service(self) -> TranslationService:
        if self._translation_service is None:
             # Log error before raising
            logger.error(f"TranslationService accessed before initialization in task {self.request.id}")
            raise RuntimeError("TranslationService not initialized. Call initialize_services first.")
        return self._translation_service

    @property
    def invoice_ninja_service(self) -> InvoiceNinjaService:
        if self._invoice_ninja_service is None:
             # Log error before raising
            logger.error(f"InvoiceNinjaService accessed before initialization in task {self.request.id}")
            raise RuntimeError("InvoiceNinjaService not initialized. Call initialize_services first.")
        return self._invoice_ninja_service

    @property
    def cache_service(self) -> CacheService:
        if self._cache_service is None:
            logger.error(f"CacheService accessed before initialization in task {self.request.id}")
            raise RuntimeError("CacheService not initialized. Call initialize_services first.")
        return self._cache_service

    @property
    def payment_service(self) -> PaymentService:
        if self._payment_service is None:
            logger.error(f"PaymentService accessed before initialization in task {self.request.id}")
            raise RuntimeError("PaymentService not initialized. Call initialize_services first.")
        return self._payment_service
    
    async def cleanup_services(self):
        """
        Cleanup async resources before the event loop closes.
        
        CRITICAL: Call this method in a finally block before returning from async functions
        that are executed with asyncio.run() (e.g., in Celery tasks). This ensures the httpx
        client's cleanup tasks complete while the event loop is still running, preventing
        "Event loop is closed" errors.
        
        Example usage:
            async def _async_task(task: BaseServiceTask):
                try:
                    await task.initialize_services()
                    # ... do work ...
                finally:
                    await task.cleanup_services()
        """
        # Close SecretsManager's httpx client
        if self._secrets_manager is not None:
            try:
                await self._secrets_manager.aclose()
                logger.debug(f"SecretsManager httpx client closed for task {self.request.id}")
                # Reset the reference so future tasks reinitialize a fresh client.
                # This prevents reuse of a closed httpx client across Celery tasks.
                self._secrets_manager = None
            except Exception as e:
                # Log but don't raise - cleanup errors shouldn't break the task
                logger.warning(f"Error closing SecretsManager in task {self.request.id}: {e}")
        
        # Close DirectusService's httpx client if it has one
        if self._directus_service is not None and hasattr(self._directus_service, 'close'):
            try:
                await self._directus_service.close()
                logger.debug(f"DirectusService httpx client closed for task {self.request.id}")
                # Reset the reference so future tasks create a new client.
                # The DirectusService wraps an AsyncClient which cannot be reused once closed.
                self._directus_service = None
            except Exception as e:
                logger.warning(f"Error closing DirectusService in task {self.request.id}: {e}")
        
        # Close CacheService's Redis client
        # CRITICAL: The async Redis client is bound to a specific event loop.
        # If not closed before asyncio.run() finishes, subsequent tasks will fail with
        # "Event loop is closed" errors because the cached client references a closed loop.
        if self._cache_service is not None and hasattr(self._cache_service, 'close'):
            try:
                await self._cache_service.close()
                logger.debug(f"CacheService Redis client closed for task {self.request.id}")
                # Reset the reference so future tasks create a fresh client bound to their event loop
                self._cache_service = None
            except Exception as e:
                logger.warning(f"Error closing CacheService in task {self.request.id}: {e}")
        
        # Also reset encryption service since it may hold a reference to the cache service
        if self._encryption_service is not None:
            self._encryption_service = None