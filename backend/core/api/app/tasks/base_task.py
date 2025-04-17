import logging
from typing import Optional
import asyncio # Keep asyncio import if initialize_services uses it

from celery import Task # Import Task for context

# Import necessary services and utilities
from app.services.directus import DirectusService
from app.services.revolut_service import RevolutService
from app.utils.encryption import EncryptionService
from app.services.s3.service import S3Service
from app.services.pdf.invoice import InvoiceTemplateService
from app.services.email_template import EmailTemplateService
from app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# --- Base Task Class for Service Initialization ---
# This helps avoid initializing services multiple times if the task retries
class BaseServiceTask(Task):
    _directus_service: Optional[DirectusService] = None
    _revolut_service: Optional[RevolutService] = None
    _encryption_service: Optional[EncryptionService] = None
    _s3_service: Optional[S3Service] = None
    _invoice_template_service: Optional[InvoiceTemplateService] = None
    _email_template_service: Optional[EmailTemplateService] = None
    _secrets_manager: Optional[SecretsManager] = None

    async def initialize_services(self):
        # Initialize SecretsManager first as others depend on it
        if self._secrets_manager is None:
            logger.debug(f"Initializing SecretsManager for task {self.request.id}")
            self._secrets_manager = SecretsManager()
            await self._secrets_manager.initialize()
            logger.debug(f"SecretsManager initialized for task {self.request.id}")
        else:
             logger.debug(f"SecretsManager already initialized for task {self.request.id}")

        # Initialize other services, passing the initialized SecretsManager
        if self._directus_service is None:
            logger.debug(f"Initializing DirectusService for task {self.request.id}")
            self._directus_service = DirectusService(secrets_manager=self._secrets_manager)
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
            self._encryption_service = EncryptionService()
            logger.debug(f"EncryptionService initialized for task {self.request.id}")
        else:
             logger.debug(f"EncryptionService already initialized for task {self.request.id}")

        if self._s3_service is None:
            logger.debug(f"Initializing S3Service for task {self.request.id}")
            self._s3_service = S3Service(secrets_manager=self._secrets_manager)
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
    def s3_service(self) -> S3Service:
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

    # Add secrets_manager property as well
    @property
    def secrets_manager(self) -> SecretsManager:
        if self._secrets_manager is None:
             # Log error before raising
            logger.error(f"SecretsManager accessed before initialization in task {self.request.id}")
            raise RuntimeError("SecretsManager not initialized. Call initialize_services first.")
        return self._secrets_manager