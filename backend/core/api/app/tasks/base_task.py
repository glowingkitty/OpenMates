import logging
from typing import Optional
import asyncio # Keep asyncio import if initialize_services uses it

from celery import Task # Import Task for context

# Import necessary services and utilities
from backend.core.api.app.services.cache import CacheService # Added for CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.revolut_service import RevolutService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.services.pdf.invoice import InvoiceTemplateService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.services.translations import TranslationService
from backend.core.api.app.services.invoiceninja.invoiceninja import InvoiceNinjaService # Import InvoiceNinjaService

logger = logging.getLogger(__name__)

# --- Base Task Class for Service Initialization ---
# This helps avoid initializing services multiple times if the task retries
class BaseServiceTask(Task):
    _directus_service: Optional[DirectusService] = None
    _revolut_service: Optional[RevolutService] = None
    _encryption_service: Optional[EncryptionService] = None
    _s3_service: Optional[S3UploadService] = None
    _invoice_template_service: Optional[InvoiceTemplateService] = None
    _email_template_service: Optional[EmailTemplateService] = None
    _secrets_manager: Optional[SecretsManager] = None
    _translation_service: Optional[TranslationService] = None
    _invoice_ninja_service: Optional[InvoiceNinjaService] = None # Add InvoiceNinjaService attribute
    _cache_service: Optional[CacheService] = None # Added CacheService

    async def initialize_services(self):
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

        if self._revolut_service is None:
            logger.debug(f"Initializing RevolutService for task {self.request.id}")
            self._revolut_service = RevolutService(secrets_manager=self._secrets_manager)
            await self._revolut_service.initialize() # Revolut service needs init
            logger.debug(f"RevolutService initialized for task {self.request.id}")
        else:
             logger.debug(f"RevolutService already initialized for task {self.request.id}")

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
            # Assuming InvoiceTemplateService doesn't need secrets_manager for init
            self._invoice_template_service = InvoiceTemplateService() # Assumes sync init
            logger.debug(f"InvoiceTemplateService initialized for task {self.request.id}")
        else:
             logger.debug(f"InvoiceTemplateService already initialized for task {self.request.id}")

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


    @property
    def directus_service(self) -> DirectusService:
        if self._directus_service is None:
            # Log error before raising
            logger.error(f"DirectusService accessed before initialization in task {self.request.id}")
            raise RuntimeError("DirectusService not initialized. Call initialize_services first.")
        return self._directus_service

    @property
    def revolut_service(self) -> RevolutService:
        if self._revolut_service is None:
             # Log error before raising
            logger.error(f"RevolutService accessed before initialization in task {self.request.id}")
            raise RuntimeError("RevolutService not initialized. Call initialize_services first.")
        return self._revolut_service

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
