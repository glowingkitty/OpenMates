# backend/core/api/app/tasks/email_tasks/issue_report_email_task.py
"""
Celery task for sending issue report emails to server owner/admin.

This module handles sending issue reports submitted by users (including non-authenticated users)
to the server owner/admin email address.

Architecture:
- The main task (send_issue_report_email) sends the email first, then uploads YAML to S3.
- If S3 upload fails, a separate retry task (retry_issue_report_s3_upload) is dispatched
  with exponential backoff. This decouples the user-facing email from the admin-tooling S3 upload.
- The retry task has its own retry logic (up to 5 attempts with exponential backoff).
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

# Maximum number of S3 upload retry attempts
S3_UPLOAD_MAX_RETRIES = 5


@app.task(name='app.tasks.email_tasks.issue_report_email_task.send_issue_report_email', base=BaseServiceTask, bind=True)
def send_issue_report_email(
    self: BaseServiceTask,
    admin_email: str,
    issue_id: Optional[str] = None,
    issue_title: str = "",
    issue_description: Optional[str] = None,
    chat_or_embed_url: Optional[str] = None,
    contact_email: Optional[str] = None,
    language: str = "en",
    timestamp: str = "",
    estimated_location: str = "",
    device_info: Optional[str] = None,
    console_logs: Optional[str] = None,
    indexeddb_report: Optional[str] = None,
    last_messages_html: Optional[str] = None,
    active_chat_sidebar_html: Optional[str] = None,
    runtime_debug_state: Optional[str] = None,
    action_history: Optional[str] = None,
    picked_element_html: Optional[str] = None,
    screenshot_presigned_url: Optional[str] = None,
    trace_ids: Optional[list] = None
) -> bool:
    """
    Celery task to send issue report email to server owner/admin.

    Args:
        admin_email: The email address of the admin/server owner to notify
        issue_id: Optional database ID for the issue record
        issue_title: The title of the reported issue
        issue_description: The description of the reported issue
        chat_or_embed_url: Optional URL to a chat or embed related to the issue
        contact_email: Optional contact email address for follow-up communication
        language: ISO 639-1 language code from the client UI (for confirmation email localisation)
        timestamp: Timestamp when the issue was reported (formatted string)
        estimated_location: Estimated geographic location based on IP address
        device_info: Optional device information for debugging (browser, screen size, touch support)
        console_logs: Optional console logs from the client (last 100 lines)
        indexeddb_report: Optional IndexedDB inspection report (metadata only, no plaintext content)
        last_messages_html: Optional rendered HTML of the last user message and assistant response
        active_chat_sidebar_html: Optional outerHTML of the active chat sidebar entry (Chat.svelte)
        runtime_debug_state: Optional JSON string with WS status, AI typing, pending uploads, sync state
        action_history: Optional last 20 user-action history entries (button names/navigation only,
                        no user-typed text content)
        picked_element_html: Optional outerHTML of the DOM element the user tapped/clicked via the
                             element picker overlay — captures the broken UI element's HTML structure

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
                self, admin_email, issue_id, issue_title, issue_description,
                chat_or_embed_url, contact_email, language, timestamp, estimated_location, device_info, console_logs,
                indexeddb_report, last_messages_html, active_chat_sidebar_html, runtime_debug_state, action_history,
                picked_element_html, screenshot_presigned_url
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


@app.task(
    name='app.tasks.email_tasks.issue_report_email_task.retry_issue_report_s3_upload',
    base=BaseServiceTask,
    bind=True,
    max_retries=S3_UPLOAD_MAX_RETRIES,
    default_retry_delay=30,  # Initial delay of 30 seconds
)
def retry_issue_report_s3_upload(
    self: BaseServiceTask,
    issue_id: str,
    yaml_content: str,
) -> bool:
    """
    Dedicated retry task for uploading issue report YAML to S3.

    This task is dispatched by the main email task when the initial S3 upload fails.
    It retries with exponential backoff (30s, 60s, 120s, 240s, 480s) up to 5 times.

    Args:
        issue_id: The database ID of the issue record to update with the S3 key
        yaml_content: The YAML content to encrypt and upload

    Returns:
        bool: True if upload succeeded, False otherwise
    """
    attempt = self.request.retries + 1
    logger.info(
        f"[S3_RETRY] Attempting S3 upload for issue {issue_id} "
        f"(attempt {attempt}/{S3_UPLOAD_MAX_RETRIES + 1}, "
        f"task_id={self.request.id if hasattr(self.request, 'id') else 'unknown'})"
    )
    try:
        result = asyncio.run(
            _async_upload_issue_yaml_to_s3(self, issue_id, yaml_content)
        )
        if result:
            logger.info(f"[S3_RETRY] Successfully uploaded issue report YAML to S3 for issue {issue_id} on attempt {attempt}")
        else:
            logger.error(f"[S3_RETRY] Upload returned False for issue {issue_id} on attempt {attempt}")
        return result
    except Exception as e:
        # Calculate backoff: 30s * 2^retry_number (30s, 60s, 120s, 240s, 480s)
        backoff = 30 * (2 ** self.request.retries)
        logger.error(
            f"[S3_RETRY] Failed S3 upload for issue {issue_id} on attempt {attempt}: {str(e)}. "
            f"{'Retrying in ' + str(backoff) + 's...' if self.request.retries < S3_UPLOAD_MAX_RETRIES else 'No more retries - giving up.'}",
            exc_info=True
        )
        if self.request.retries < S3_UPLOAD_MAX_RETRIES:
            raise self.retry(exc=e, countdown=backoff)
        return False


async def _async_upload_issue_yaml_to_s3(
    task: BaseServiceTask,
    issue_id: str,
    yaml_content: str,
) -> bool:
    """
    Async implementation for uploading issue report YAML to S3.
    Used by both the main task and the retry task.
    """
    try:
        await task.initialize_services()

        import uuid
        from datetime import datetime, timezone

        # Encrypt the YAML content
        encrypted_yaml = await task.encryption_service.encrypt_issue_report_data(yaml_content)
        encrypted_yaml_bytes = encrypted_yaml.encode('utf-8')

        # Generate unique S3 object key
        timestamp_str = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        unique_id = uuid.uuid4().hex[:8]
        s3_object_key = f"issue-reports/{timestamp_str}_{unique_id}.yaml.encrypted"

        # Upload encrypted YAML to S3
        await task.s3_service.upload_file(
            bucket_key='issue_logs',
            file_key=s3_object_key,
            content=encrypted_yaml_bytes,
            content_type='application/octet-stream'
        )
        logger.info(f"[S3_RETRY] Uploaded encrypted issue report YAML to S3: {s3_object_key}")

        # Encrypt the S3 object key for database storage
        encrypted_yaml_s3_key = await task.encryption_service.encrypt_issue_report_data(s3_object_key)

        # Update the issue record in database with the S3 key
        await task.directus_service.update_item(
            "issues",
            issue_id,
            {"encrypted_issue_report_yaml_s3_key": encrypted_yaml_s3_key}
        )
        logger.info(f"[S3_RETRY] Updated issue {issue_id} with encrypted YAML S3 key")
        return True

    finally:
        try:
            await task.cleanup_services()
        except Exception as cleanup_error:
            logger.warning(f"[S3_RETRY] Error during cleanup: {str(cleanup_error)}", exc_info=True)


async def _async_send_issue_report_email(
    task: BaseServiceTask,
    admin_email: str,
    issue_id: Optional[str] = None,
    issue_title: str = "",
    issue_description: Optional[str] = None,
    chat_or_embed_url: Optional[str] = None,
    contact_email: Optional[str] = None,
    language: str = "en",
    timestamp: str = "",
    estimated_location: str = "",
    device_info: Optional[str] = None,
    console_logs: Optional[str] = None,
    indexeddb_report: Optional[str] = None,
    last_messages_html: Optional[str] = None,
    active_chat_sidebar_html: Optional[str] = None,
    runtime_debug_state: Optional[str] = None,
    action_history: Optional[str] = None,
    picked_element_html: Optional[str] = None,
    screenshot_presigned_url: Optional[str] = None
) -> bool:
    """
    Async implementation for sending issue report email.

    Args:
        task: The Celery base task instance
        admin_email: Admin email address to send the report to
        issue_id: Database ID of the issue record (for S3 upload linking)
        issue_title: Issue title
        issue_description: Formatted description with user flow / expected / actual behaviour
        chat_or_embed_url: Optional share URL for active chat or embed
        contact_email: Optional reporter email for confirmation
        language: ISO 639-1 language code for localised confirmation email
        timestamp: Human-readable report timestamp
        estimated_location: Geo-location string derived from IP
        device_info: Serialised device info (browser, viewport, touch)
        console_logs: Last 100 client-side console log lines
        indexeddb_report: IndexedDB inspection metadata (no plaintext content)
        last_messages_html: Rendered HTML of last user + assistant messages
        active_chat_sidebar_html: outerHTML of the active chat sidebar entry (Chat.svelte)
        runtime_debug_state: JSON string with WS status, AI typing, pending uploads, sync state
        action_history: Last 20 user-action history entries (button names /
                        navigation only — no user-typed text content)

    Note: This function ensures proper cleanup of async resources (like httpx clients)
    before the event loop closes to prevent "Event loop is closed" errors.
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

        # Prepare consolidated YAML attachment
        attachments = []

        # Create a consolidated YAML file with all issue report data.
        # NOTE: console_logs and docker_compose_logs are intentionally NOT stored here anymore.
        # Both are already persisted in OpenObserve (console_logs via push_issue_logs with
        # job=client-issue-report, backend logs continuously via Promtail/container-logs stream).
        # Use `debug.py issue <id> --timeline` to query them live in a unified chronological view.
        import yaml
        import base64
        from datetime import datetime, timezone

        issue_report_data = {
            'issue_report': {
                'metadata': {
                    'issue_id': issue_id,  # Database ID for easy admin lookup
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
                # Logs are omitted from S3 YAML — query live via OpenObserve:
                #   debug.py issue <id> --timeline
                # IndexedDB inspection report contains ONLY metadata (timestamps, versions, encrypted content lengths)
                # NO plaintext chat content is included - safe for debugging while preserving user privacy
                'indexeddb_inspection': indexeddb_report.strip() if indexeddb_report and indexeddb_report.strip() else None,
                # Rendered HTML of the last user message and assistant response
                # Helps debug rendering issues by showing exactly what the user saw
                'last_messages_html': last_messages_html.strip() if last_messages_html and last_messages_html.strip() else None,
                # outerHTML of the active chat entry in the sidebar (Chat.svelte) at submit time.
                # Shows title, status label, typing indicator text and category icon state.
                # Useful for "wrong chat active" and "typing indicator stuck" bugs.
                'active_chat_sidebar_html': active_chat_sidebar_html.strip() if active_chat_sidebar_html and active_chat_sidebar_html.strip() else None,
                # Runtime state snapshot: WS status, online status, AI typing, pending uploads, sync state.
                # JSON string — helps debug message-sending and sync issues.
                'runtime_debug_state': runtime_debug_state.strip() if runtime_debug_state and runtime_debug_state.strip() else None,
                # User-action history: last 20 interactions (button names / navigation only)
                # NO user-typed text content is ever included — only developer-authored labels
                # (data-action attrs, aria-labels, placeholder text, class names)
                'action_history': action_history.strip() if action_history and action_history.strip() else None,
                # outerHTML of the DOM element the user tapped/clicked via the element picker overlay.
                # Captures the exact HTML structure of a broken UI element for debugging layout,
                # rendering, or content issues.
                'picked_element_html': picked_element_html.strip() if picked_element_html and picked_element_html.strip() else None,
                # Pre-signed URL for the screenshot PNG (valid 7 days from report time).
                # The image is stored unencrypted in the private issue_logs S3 bucket so
                # admins and LLMs can load it directly without any decryption step.
                'screenshot_presigned_url': screenshot_presigned_url if screenshot_presigned_url else None
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
        
        # Encrypt and upload YAML file to S3 if issue_id is provided.
        # If the upload fails, dispatch a dedicated retry task with exponential backoff
        # so the email can still be sent immediately (user-facing) while S3 upload retries
        # independently (admin tooling).
        if issue_id:
            try:
                # Encrypt the YAML content
                encrypted_yaml = await task.encryption_service.encrypt_issue_report_data(yaml_content)
                encrypted_yaml_bytes = encrypted_yaml.encode('utf-8')
                
                # Generate unique S3 object key
                import uuid
                from datetime import datetime, timezone
                timestamp_str = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
                unique_id = uuid.uuid4().hex[:8]
                s3_object_key = f"issue-reports/{timestamp_str}_{unique_id}.yaml.encrypted"
                
                # Upload encrypted YAML to S3
                await task.s3_service.upload_file(
                    bucket_key='issue_logs',
                    file_key=s3_object_key,
                    content=encrypted_yaml_bytes,
                    content_type='application/octet-stream'
                )
                logger.info(f"Uploaded encrypted issue report YAML to S3: {s3_object_key}")
                
                # Encrypt the S3 object key for database storage
                encrypted_yaml_s3_key = await task.encryption_service.encrypt_issue_report_data(s3_object_key)
                
                # Update the issue record in database with the S3 key
                await task.directus_service.update_item(
                    "issues",
                    issue_id,
                    {"encrypted_issue_report_yaml_s3_key": encrypted_yaml_s3_key}
                )
                logger.info(f"Updated issue {issue_id} with encrypted YAML S3 key")
            except Exception as e:
                logger.error(
                    f"Failed to upload issue report YAML to S3 for issue {issue_id}: {str(e)}. "
                    f"Dispatching retry task with exponential backoff.",
                    exc_info=True
                )
                # Dispatch a dedicated retry task for S3 upload with exponential backoff.
                # The email will still be sent below — this decouples user-facing email delivery
                # from the admin-tooling S3 upload.
                try:
                    from backend.core.api.app.tasks.celery_config import app as celery_app
                    celery_app.send_task(
                        name='app.tasks.email_tasks.issue_report_email_task.retry_issue_report_s3_upload',
                        kwargs={
                            "issue_id": issue_id,
                            "yaml_content": yaml_content,
                        },
                        queue='email',
                        countdown=30,  # First retry after 30 seconds
                    )
                    logger.info(f"Dispatched S3 upload retry task for issue {issue_id} (first retry in 30s)")
                except Exception as dispatch_error:
                    logger.error(
                        f"CRITICAL: Failed to dispatch S3 retry task for issue {issue_id}: {str(dispatch_error)}. "
                        f"The YAML report will NOT be available for this issue.",
                        exc_info=True
                    )
        elif not issue_id:
            logger.warning(
                "No issue_id provided to email task - skipping S3 upload. "
                "This means the Directus record creation likely failed in the API route."
            )

        # Process contact email if provided
        contact_email_formatted = contact_email if contact_email else "Not provided"
        
        # Prepare email context with sanitized data
        email_context = {
            "darkmode": True,  # Default to dark mode for issue report emails
            "issue_id": issue_id,  # Include issue ID for easy admin lookup via /v1/admin/debug/issues/{issue_id}
            "issue_title": sanitized_title,
            "issue_description": sanitized_description,
            "chat_or_embed_url": sanitized_url,
            "contact_email": contact_email_formatted,
            "timestamp": timestamp,
            "estimated_location": estimated_location,
            "device_info": device_info_formatted,
            # Pre-signed URL for the screenshot PNG — included in the email so admins
            # and LLMs can view the screenshot directly without needing the inspect script.
            "screenshot_presigned_url": screenshot_presigned_url if screenshot_presigned_url else None
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
        
        # Send confirmation email to the user who reported the issue (if they provided an email)
        # This email contains only the basics: title, description, timestamp, issue ID
        # No logs, device info, or other technical debugging data
        if contact_email and contact_email != "Not provided":
            try:
                logger.info(f"Sending issue report confirmation email to reporter: {contact_email}")
                
                # Prepare confirmation email context (only basic report info)
                confirmation_context = {
                    "darkmode": True,
                    "issue_id": issue_id,
                    "issue_title": sanitized_title,
                    "issue_description": sanitized_description if sanitized_description else None,
                    "timestamp": timestamp,
                }
                
                confirmation_success = await task.email_template_service.send_email(
                    template="issue_report_confirmation",
                    recipient_email=contact_email,
                    context=confirmation_context,
                    lang=language,  # Use the client's UI language passed from the API route
                )
                
                if confirmation_success:
                    logger.info(
                        f"Successfully sent issue report confirmation email to {contact_email} "
                        f"for issue '{issue_title[:50]}...'"
                    )
                else:
                    logger.error(
                        f"Failed to send issue report confirmation email to {contact_email} - "
                        f"send_email() returned False. The admin email was sent successfully."
                    )
            except Exception as confirmation_error:
                # Log the error but don't fail the overall task - the admin email was already sent
                logger.error(
                    f"Error sending issue report confirmation email to {contact_email}: "
                    f"{str(confirmation_error)}. The admin email was sent successfully.",
                    exc_info=True
                )
        else:
            logger.info("No contact email provided - skipping issue report confirmation email to reporter")
        
        return True
        
    except Exception as e:
        logger.error(f"Error sending issue report email: {str(e)}", exc_info=True)
        return False
    
    finally:
        # CRITICAL: Close async resources (like httpx clients) before the event loop closes
        # This prevents "Event loop is closed" errors during cleanup
        # Use the cleanup_services method from BaseServiceTask which handles SecretsManager and DirectusService
        try:
            await task.cleanup_services()
            logger.debug("Task services cleaned up successfully")
        except Exception as cleanup_error:
            # Log but don't raise - we're in cleanup and don't want to mask the original error
            logger.warning(
                f"Error during task cleanup: {str(cleanup_error)}. "
                f"This is non-critical but should be investigated.",
                exc_info=True
            )
