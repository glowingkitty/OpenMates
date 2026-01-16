import logging
import asyncio
from typing import Dict, Any, Optional

# Import the Celery app
from backend.core.api.app.tasks.celery_config import app

# Import necessary services and utilities
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)

@app.task(name='app.tasks.email_tasks.account_created_email_task.send_account_created_email', bind=True)
def send_account_created_email(self, email: str, account_id: str, language: str = "en", darkmode: bool = False) -> bool:
    """
    Send an 'Account created' confirmation email to the user.
    """
    logger.info(f"Starting account created email task for {email[:2]}***")
    try:
        result = asyncio.run(
            _async_send_account_created_email(
                email, account_id, language, darkmode
            )
        )
        logger.info(f"Account created email task completed for {email[:2]}***")
        return result
    except Exception as e:
        logger.error(f"Failed to run account created email task for {email[:2]}***: {str(e)}", exc_info=True)
        return False

async def _async_send_account_created_email(email: str, account_id: str, language: str, darkmode: bool) -> bool:
    """Async implementation of send_account_created_email."""
    secrets_manager = SecretsManager()
    
    try:
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        
        # Determine webapp URL for the delete link
        from backend.core.api.app.utils.server_mode import get_hosting_domain
        import os
        
        is_dev = os.getenv("ENVIRONMENT", "production").lower() in ("development", "dev", "test")
        hosting_domain = get_hosting_domain()
        
        if hosting_domain:
            protocol = "https" if not is_dev else "http"
            base_webapp_url = f"{protocol}://{hosting_domain}"
        else:
            base_webapp_url = os.getenv("WEBAPP_URL", "https://openmates.org" if not is_dev else "http://localhost:5173")
            
        if base_webapp_url.endswith('/'):
            base_webapp_url = base_webapp_url[:-1]
            
        delete_account_link = f"{base_webapp_url}/#settings/account/delete/{account_id}"
        
        # Prepare context for the template
        context = {
            'email': email,
            'account_id': account_id,
            'delete_account_link': delete_account_link,
            'darkmode': darkmode
        }
        
        # Send the email
        success = await email_template_service.send_email(
            template="account-created",
            recipient_email=email,
            context=context,
            lang=language
        )
        
        return success
        
    except Exception as e:
        logger.error(f"Error in _async_send_account_created_email for {email[:2]}***: {str(e)}", exc_info=True)
        return False
    finally:
        await secrets_manager.aclose()
