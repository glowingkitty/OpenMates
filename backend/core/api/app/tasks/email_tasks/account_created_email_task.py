import logging
import asyncio

# Import the Celery app
from backend.core.api.app.tasks.celery_config import app
from backend.shared.python_utils.frontend_url import get_frontend_base_url

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
        
        base_webapp_url = get_frontend_base_url()
        delete_account_link = f"{base_webapp_url}/#settings/account/delete/{account_id}"
        recovery_key_settings_url = f"{base_webapp_url}/#settings/account/security/recovery-key"
        passkeys_settings_url = f"{base_webapp_url}/#settings/account/security/passkeys"
        twofa_settings_url = f"{base_webapp_url}/#settings/account/security/2fa"
        export_account_settings_url = f"{base_webapp_url}/#settings/account/export"
        
        # Prepare context for the template
        context = {
            'email': email,
            'account_id': account_id,
            'delete_account_link': delete_account_link,
            'recovery_key_settings_url': recovery_key_settings_url,
            'passkeys_settings_url': passkeys_settings_url,
            'twofa_settings_url': twofa_settings_url,
            'export_account_settings_url': export_account_settings_url,
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
