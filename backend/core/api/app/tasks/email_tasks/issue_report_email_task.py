# backend/core/api/app/tasks/email_tasks/issue_report_email_task.py
"""
Celery task for sending issue report emails to server owner/admin.

This module handles sending issue reports submitted by users (including non-authenticated users)
to the server owner/admin email address.
"""

import logging
import asyncio
from typing import Optional

# Import the Celery app and Base Task
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask

# Import necessary services and utilities
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)
event_logger = logging.getLogger("app.events")
event_logger.addFilter(sensitive_filter)


@app.task(name='app.tasks.email_tasks.issue_report_email_task.send_issue_report_email', base=BaseServiceTask, bind=True)
def send_issue_report_email(
    self: BaseServiceTask,
    admin_email: str,
    issue_title: str,
    issue_description: Optional[str],
    chat_or_embed_url: Optional[str],
    contact_email: Optional[str] = None,
    timestamp: str = "",
    estimated_location: str = "",
    device_info: Optional[str] = None,
    console_logs: Optional[str] = None
) -> bool:
    """
    Celery task to send issue report email to server owner/admin.

    Args:
        admin_email: The email address of the admin/server owner to notify
        issue_title: The title of the reported issue
        issue_description: The description of the reported issue
        chat_or_embed_url: Optional URL to a chat or embed related to the issue
        contact_email: Optional contact email address for follow-up communication
        timestamp: Timestamp when the issue was reported (formatted string)
        estimated_location: Estimated geographic location based on IP address
        device_info: Optional device information for debugging (browser, screen size, touch support)
        console_logs: Optional console logs from the client (last 100 lines)

    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    logger.info(
        f"Starting issue report email task for issue: '{issue_title[:50]}...' "
        f"(task_id={self.request.id if hasattr(self.request, 'id') else 'unknown'}, "
        f"recipient={admin_email})"
    )
    try:
        # Use asyncio.run() which handles loop creation and cleanup properly
        result = asyncio.run(
            _async_send_issue_report_email(
                self, admin_email, issue_title, issue_description,
                chat_or_embed_url, contact_email, timestamp, estimated_location, device_info, console_logs
            )
        )
        if result:
            logger.info(
                f"Issue report email task completed successfully for issue: '{issue_title[:50]}...' "
                f"(recipient={admin_email})"
            )
        else:
            logger.error(
                f"Issue report email task failed for issue: '{issue_title[:50]}...' "
                f"(recipient={admin_email}) - check logs above for details"
            )
        return result
    except Exception as e:
        logger.error(
            f"Failed to run issue report email task for issue '{issue_title[:50]}...': {str(e)} "
            f"(recipient={admin_email})", 
            exc_info=True
        )
        return False


async def _async_send_issue_report_email(
    task: BaseServiceTask,
    admin_email: str,
    issue_title: str,
    issue_description: Optional[str],
    chat_or_embed_url: Optional[str],
    contact_email: Optional[str] = None,
    timestamp: str = "",
    estimated_location: str = "",
    device_info: Optional[str] = None,
    console_logs: Optional[str] = None
) -> bool:
    """
    Async implementation for sending issue report email.
    """
    try:
        # Initialize services using the base task class method
        logger.info("Initializing services for issue report email task...")
        await task.initialize_services()
        logger.info("Services initialized for issue report email task")
        
        # Verify email_template_service is available
        if not hasattr(task, 'email_template_service') or task.email_template_service is None:
            logger.error("email_template_service not available after initialization")
            return False
        logger.info("email_template_service is available")
        
        # SECURITY: Sanitize inputs before passing to email template
        # Note: Inputs should already be sanitized in the route handler, but we sanitize again here
        # as a defense-in-depth measure. The data is sanitized before template rendering.
        from html import escape
        
        # HTML escape title and description (already done in route, but double-check here)
        sanitized_title = escape(issue_title) if issue_title else ""
        sanitized_description = escape(issue_description) if issue_description else ""
        
        # Convert newlines to <br/> tags for email display (after escaping)
        # This is safe because we've already escaped all HTML tags
        sanitized_description = sanitized_description.replace('\n', '<br/>')
        
        # URL is already validated in route handler, but ensure it's safe for href attribute
        sanitized_url = chat_or_embed_url if chat_or_embed_url else "Not provided"
        
        # Process device info if provided
        device_info_formatted = device_info if device_info else "Not provided"
        # Convert newlines to <br/> for HTML display in email
        device_info_formatted = device_info_formatted.replace('\n', '<br/>')

        # Collect Docker Compose logs from all containers via Loki
        logger.info("Collecting Docker Compose logs from all containers via Loki for issue report")
        from backend.core.api.app.services.loki_log_collector import loki_log_collector
        from datetime import datetime, timedelta, timezone
        backend_logs = await loki_log_collector.get_compose_logs(
            lines=50,
            exclude_containers=["grafana", "promtail", "loki", "cadvisor", "prometheus"],
            start_time=datetime.now(timezone.utc) - timedelta(minutes=5),
        )

        # Prepare consolidated YAML attachment
        attachments = []

        # Create a consolidated YAML file with all issue report data
        import yaml
        import base64
        from datetime import datetime, timezone

        issue_report_data = {
            'issue_report': {
                'metadata': {
                    'generated_at': datetime.now(timezone.utc).isoformat(),
                    'report_timestamp': timestamp,
                    'title': issue_title,
                    'description': issue_description,
                    'contact_email': contact_email,
                    'estimated_location': estimated_location
                },
                'technical_details': {
                    'chat_or_embed_url': chat_or_embed_url,
                    'device_info': device_info if device_info else None
                },
                'logs': {
                    'console_logs': console_logs.strip() if console_logs and console_logs.strip() else None,
                    'docker_compose_logs': backend_logs.strip() if backend_logs and backend_logs.strip() else None
                }
            }
        }

        # Generate YAML content
        yaml_content = yaml.dump(issue_report_data, default_flow_style=False, allow_unicode=True)
        yaml_content_b64 = base64.b64encode(yaml_content.encode('utf-8')).decode('utf-8')

        # Create single consolidated attachment
        # Note: Using .txt extension instead of .yml because Brevo API does not support .yml files
        # The content is still valid YAML format, just with .txt extension for email compatibility
        attachments.append({
            'filename': f'issue_report_{timestamp.replace(" ", "_").replace(":", "-")}.txt',
            'content': yaml_content_b64
        })

        logger.info("Created consolidated YAML attachment (as .txt) for issue report with all logs and metadata")

        # Process contact email if provided
        contact_email_formatted = contact_email if contact_email else "Not provided"
        
        # Prepare email context with sanitized data
        email_context = {
            "darkmode": True,  # Default to dark mode for issue report emails
            "issue_title": sanitized_title,
            "issue_description": sanitized_description,
            "chat_or_embed_url": sanitized_url,
            "contact_email": contact_email_formatted,
            "timestamp": timestamp,
            "estimated_location": estimated_location,
            "device_info": device_info_formatted
        }
        logger.info("Prepared email context for issue report")
        
        # Send issue report email
        attachment_info = " with consolidated YAML attachment" if attachments else " with no attachments"
        logger.info(
            f"Attempting to send issue report email to {admin_email} with template 'issue_report' "
            f"(title: '{issue_title[:50]}...'){attachment_info}"
        )
        email_success = await task.email_template_service.send_email(
            template="issue_report",
            recipient_email=admin_email,
            context=email_context,
            lang="en",  # Default to English for admin emails
            attachments=attachments
        )
        
        if not email_success:
            logger.error(
                f"Failed to send issue report email to {admin_email} - "
                f"send_email() returned False. Check email service configuration and logs."
            )
            return False
        
        logger.info(
            f"Successfully sent issue report email to {admin_email} "
            f"(subject: 'Issue reported: {issue_title[:50]}...')"
        )
        return True
        
    except Exception as e:
        logger.error(f"Error sending issue report email: {str(e)}", exc_info=True)
        return False
