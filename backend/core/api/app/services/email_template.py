import os
import logging
import re
import base64
import yaml
from typing import Dict, Any, Optional, Tuple, Union
import aiohttp
import json
from pathlib import Path
from mjml import mjml2html
from jinja2 import Template, Environment, FileSystemLoader, select_autoescape
from premailer import transform  # Add this import for CSS inlining
import cssutils  # Add this import to configure cssutils logger
import string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys
from html.parser import HTMLParser
from urllib.parse import urlparse

from backend.core.api.app.services.translations import TranslationService
from backend.core.api.app.services.email.config_loader import load_shared_urls, add_shared_urls_to_context
from backend.core.api.app.services.email.variable_processor import process_template_variables
from backend.core.api.app.services.email.renderer import render_mjml_template
from backend.core.api.app.services.email.mjml_processor import image_cache
from backend.core.api.app.services.email.brevo_provider import BrevoProvider
from backend.core.api.app.services.email.mailjet_provider import MailjetProvider
from backend.core.api.app.utils.log_filters import SensitiveDataFilter  # Import the filter
from backend.core.api.app.utils.secrets_manager import SecretsManager # Import SecretsManager

# Configure cssutils logger to suppress email-specific CSS property warnings
cssutils.log.setLevel(logging.ERROR)  # Only show ERROR level messages from cssutils

# Configure our logger with direct output to ensure visibility
logger = logging.getLogger(__name__)

# Make sure this module's logger passes all messages through

# Apply sensitive data filter to this logger
logger.addFilter(SensitiveDataFilter())

# Force this module's logger to have a direct console handler to ensure output
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False  # Don't pass to root logger to avoid duplicates


class HTMLToTextParser(HTMLParser):
    """
    HTML parser that extracts plain text content from HTML.
    Used to generate plain text versions of emails for better deliverability.
    """
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.current_text = []
        self.skip_tags = {'script', 'style', 'head', 'meta', 'link'}
        self.in_skip_tag = False
        
    def handle_starttag(self, tag, attrs):
        """Handle opening HTML tags."""
        if tag.lower() in self.skip_tags:
            self.in_skip_tag = True
        elif tag.lower() == 'br':
            self.current_text.append('\n')
        elif tag.lower() == 'p':
            if self.current_text and not self.current_text[-1].endswith('\n'):
                self.current_text.append('\n')
        elif tag.lower() == 'div':
            if self.current_text and not self.current_text[-1].endswith('\n'):
                self.current_text.append('\n')
                
    def handle_endtag(self, tag):
        """Handle closing HTML tags."""
        if tag.lower() in self.skip_tags:
            self.in_skip_tag = False
        elif tag.lower() in ('p', 'div', 'section'):
            if self.current_text and not self.current_text[-1].endswith('\n'):
                self.current_text.append('\n')
                
    def handle_data(self, data):
        """Handle text content."""
        if not self.in_skip_tag:
            # Clean up whitespace but preserve line breaks
            cleaned = re.sub(r'\s+', ' ', data.strip())
            if cleaned:
                self.current_text.append(cleaned)
                
    def get_text(self) -> str:
        """Get the extracted plain text."""
        text = ''.join(self.current_text)
        # Clean up excessive whitespace and line breaks
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Max 2 consecutive newlines
        text = re.sub(r'[ \t]+', ' ', text)  # Normalize spaces
        return text.strip()


def html_to_plain_text(html_content: str) -> str:
    """
    Convert HTML content to plain text for email deliverability.
    
    This is critical for spam prevention - emails without plain text versions
    are much more likely to be flagged as spam.
    
    Args:
        html_content: HTML content to convert
        
    Returns:
        Plain text version of the content
    """
    try:
        parser = HTMLToTextParser()
        parser.feed(html_content)
        return parser.get_text()
    except Exception as e:
        logger.warning(f"Error converting HTML to plain text: {str(e)}, using fallback")
        # Fallback: simple regex-based extraction
        # Remove script and style tags
        text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Remove all HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Decode HTML entities (basic ones)
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        return text.strip()

class EmailTemplateService:
    """
    Service for rendering and sending email templates.
    
    Supports multiple email providers:
    - Brevo (default, EU-based, GDPR-compliant)
    - Mailjet (fallback option)
    """
    
    def __init__(self, secrets_manager: SecretsManager):
        """Initialize the email template service with template directory and SecretsManager."""
        self.secrets_manager = secrets_manager
        # Path to email templates directory
        self.templates_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "templates", "email"
        )
        
        # Create templates directory if it doesn't exist
        os.makedirs(self.templates_dir, exist_ok=True)
        
        # Initialize translation service
        self.translation_service = TranslationService()
        
        # Load shared URL configuration
        self.shared_urls = load_shared_urls()
        
        # Email provider configuration
        # Default provider: Brevo (EU-based, GDPR-compliant)
        # Can be overridden via EMAIL_PROVIDER environment variable: "brevo" or "mailjet"
        self.email_provider = os.getenv("EMAIL_PROVIDER", "brevo").lower()
        
        # Provider instances will be created in send_email method after fetching credentials
        self._brevo_provider = None
        self._mailjet_provider = None
        
        # Default sender info
        self.default_sender_name = os.getenv("EMAIL_SENDER_NAME", "OpenMates")
        self.default_sender_email = os.getenv("EMAIL_SENDER_EMAIL", "noreply@openmates.org")
        
        logger.info(f"Email template service initialized with templates directory: {self.templates_dir}")
        logger.info(f"Default email provider: {self.email_provider.upper()}")
    
    def render_template(
        self, 
        template_name: str,
        context: Dict[str, Any] = None,
        lang: str = "en",
        return_context: bool = False,
    ) -> Union[str, Tuple[str, Dict[str, Any]]]:
        """
        Render an email template with the given context.
        
        Args:
            template_name: Name of the template to render
            context: Dictionary of variables to pass to the template
            lang: Language code for translations
            
        Returns:
            Rendered HTML content, optionally with the processed context used for rendering.
        """
        if context is None:
            context = {}
            
        # Add language to context
        context["lang"] = lang
        
        try:
            # Create a working copy of the context
            working_context = context.copy()
            
            # Add shared URLs to context
            working_context = add_shared_urls_to_context(working_context, self.shared_urls)
            
            # Process and set default values for variables
            working_context = process_template_variables(working_context)
            
            # Load translations and pass context variables to allow variable replacement
            logger.debug(f"Loading translations for language: {lang}")
            working_context['t'] = self.translation_service.get_translations(lang, variables=working_context)
            
            # Render the template using the modular renderer
            html_content = render_mjml_template(
                templates_dir=self.templates_dir,
                template_name=template_name,
                context=working_context
            )

            if return_context:
                return html_content, working_context
            return html_content
            
        except Exception as e:
            logger.error(f"Error rendering email template '{template_name}': {str(e)}", exc_info=True)
            raise
    
    async def send_email(
        self,
        template: str,
        recipient_email: str,
        recipient_name: str = "",
        context: Dict[str, Any] = None,
        subject: str = None,
        sender_name: str = None,
        sender_email: str = None,
        lang: str = "en",
        attachments: Optional[list] = None # Add attachments parameter
    ) -> bool:
        """
        Send an email using Brevo (default) or Mailjet (fallback) with a rendered template.
        
        Args:
            template: Template name to use
            recipient_email: Email address of the recipient
            recipient_name: Name of the recipient (optional)
            context: Dictionary of variables for the template
            subject: Custom subject line (uses template default if None)
            sender_name: Name of sender (uses default if None)
            sender_email: Email of sender (uses default if None)
            lang: Language code for translations
            attachments: Optional list of attachments (dicts with 'filename', 'content' base64 encoded)
            
        Returns:
            True if email was sent successfully, False otherwise
        """
        # Determine which provider to use (default: Brevo)
        provider = self.email_provider
        
        # Try to get Brevo API key first (default provider)
        brevo_api_key = await self.secrets_manager.get_secret(
            secret_path="kv/data/providers/brevo",
            secret_key="api_key"
        )
        
        # Try to get Mailjet credentials (fallback)
        mailjet_api_key = await self.secrets_manager.get_secret(
            secret_path="kv/data/providers/mailjet",
            secret_key="api_key"
        )
        mailjet_api_secret = await self.secrets_manager.get_secret(
            secret_path="kv/data/providers/mailjet",
            secret_key="api_secret"
        )
        
        # Determine which provider to actually use
        use_brevo = False
        use_mailjet = False
        
        if provider == "brevo" and brevo_api_key:
            use_brevo = True
            logger.debug("Using Brevo as email provider")
        elif provider == "brevo" and not brevo_api_key:
            logger.warning("Brevo selected but API key not found, falling back to Mailjet")
            if mailjet_api_key and mailjet_api_secret:
                use_mailjet = True
            else:
                logger.error("Cannot send email: Neither Brevo nor Mailjet credentials found")
                return False
        elif provider == "mailjet" and mailjet_api_key and mailjet_api_secret:
            use_mailjet = True
            logger.debug("Using Mailjet as email provider")
        elif provider == "mailjet" and (not mailjet_api_key or not mailjet_api_secret):
            logger.warning("Mailjet selected but credentials not found, trying Brevo fallback")
            if brevo_api_key:
                use_brevo = True
            else:
                logger.error("Cannot send email: Neither Mailjet nor Brevo credentials found")
                return False
        else:
            # Default: try Brevo first, then Mailjet
            if brevo_api_key:
                use_brevo = True
                logger.debug("Using Brevo as email provider (default)")
            elif mailjet_api_key and mailjet_api_secret:
                use_mailjet = True
                logger.debug("Using Mailjet as email provider (Brevo not available)")
            else:
                logger.error("Cannot send email: No email provider credentials found (Brevo or Mailjet)")
            return False
        try:
            # Initialize default context if needed
            if context is None:
                context = {}

            # Ensure recipient email is available to the template variable processor (e.g., block_list_url deep link).
            # SensitiveDataFilter will redact this if it ever appears in logs.
            context.setdefault("recipient_email", recipient_email)
                
            # Set defaults for sender
            sender_name = sender_name or self.default_sender_name
            sender_email = sender_email or self.default_sender_email
            
            # Get translations for the current language
            translations = self.translation_service.get_translations(lang, variables=context)
            
            # Get the subject from translations if not provided
            if not subject:
                if template == "confirm-email":
                    subject_key = "email.this_is_your_email_code.text"
                    # For confirm-email template, ensure the code is directly formatted into the subject
                    if "code" in context:
                        # Get the translation template
                        subject_template = self.translation_service.get_nested_translation(subject_key, lang, {})
                        # Manually format the code into the subject
                        subject = subject_template.format(code=context["code"])
                    else:
                        subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                elif template == "purchase-confirmation":
                    subject_key = "email.purchase_confirmation.text"
                    if "invoice_id" in context:
                        # Get the translation template
                        subject_template = self.translation_service.get_nested_translation(subject_key, lang, {})
                        # Manually format the invoice_id into the subject
                        subject = subject_template.format(invoice_id=context["invoice_id"])
                    else:
                        subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                elif template == "support-contribution-confirmation":
                    subject_key = "email.support_contribution_confirmation.text"
                    if "receipt_id" in context:
                        subject_template = self.translation_service.get_nested_translation(subject_key, lang, {})
                        subject = subject_template.format(receipt_id=context["receipt_id"])
                    else:
                        subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                elif template == "refund-confirmation":
                    subject_key = "email.refund_confirmation.text"
                    if "credit_note_id" in context:
                        # Get the translation template
                        subject_template = self.translation_service.get_nested_translation(subject_key, lang, {})
                        # Manually format the credit_note_id into the subject
                        subject = subject_template.format(credit_note_id=context["credit_note_id"])
                    else:
                        subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                elif template == "new-device-login":
                    subject_key = "email.security_alert_login_from_new_device.text"
                    subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                elif template == "backup-code-was-used":
                    subject_key = "email.security_alert_backup_code_was_used.text"
                    subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                elif template == "recovery-key-was-used":
                    subject_key = "email.security_alert_recovery_key_was_used.text"
                    subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                elif template == "signup_milestone":
                    subject_key = "email.signup_milestone.text"
                    subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                elif template == "newsletter-confirmation-request":
                    subject_key = "email.newsletter_confirmation_request.subject.text"
                    subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                elif template == "newsletter-confirmed":
                    subject_key = "email.newsletter_confirmed.subject.text"
                    subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                elif template == "newsletter":
                    subject_key = "email.newsletter.subject.text"
                    subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                elif template == "issue_report":
                    subject_key = "email.issue_report.title.text"
                    # The translation contains {issue_title} which needs to be replaced
                    if "issue_title" in context:
                        subject_template = self.translation_service.get_nested_translation(subject_key, lang, {})
                        subject = subject_template.format(issue_title=context["issue_title"])
                    else:
                        subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                elif template == "community_share_notification":
                    subject_key = "email.community_share_notification.subject.text"
                    # The translation contains {chat_title} which needs to be replaced
                    if "chat_title" in context:
                        subject_template = self.translation_service.get_nested_translation(subject_key, lang, {})
                        subject = subject_template.format(chat_title=context["chat_title"])
                    else:
                        subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                else:
                    subject_key = f"email.{template}.subject"
                    subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                
                # If key not found, use default
                if subject == subject_key:
                    subject = f"Message from {self.default_sender_name}"
                
            # Add translations to context
            if 't' not in context:
                context['t'] = translations
                
            # Render the HTML template and capture the processed context used for rendering
            html_content, render_context = self.render_template(template, context, lang, return_context=True)
            
            # Generate plain text version for better deliverability
            # This is critical for spam prevention - emails without plain text are often flagged
            plain_text_content = html_to_plain_text(html_content)
            
            # Determine if this is a transactional email (no unsubscribe needed)
            # Transactional emails: confirm-email, new-device-login, backup-code-was-used, etc.
            # These are essential account-related emails that users can't unsubscribe from
            transactional_templates = {
                'confirm-email', 'new-device-login', 'backup-code-was-used', 
                'recovery-key-was-used', 'purchase-confirmation', 'refund-confirmation', 
                'signup_milestone', 'issue_report', 'community_share_notification'
            }
            is_transactional = template in transactional_templates
            
            # For transactional emails, use mailto: support link instead of unsubscribe
            # This satisfies providers that prefer List-Unsubscribe while being appropriate for transactional emails
            # For non-transactional emails (if any), prefer a proper unsubscribe URL provided by the caller.
            support_email = render_context.get('contact_email', self.default_sender_email)

            list_unsubscribe_urls: list[str] = []
            if is_transactional:
                # Transactional emails: include a mailto: method for user support.
                list_unsubscribe_urls.append(f"mailto:{support_email}?subject=Email%20Preferences")
            else:
                # Marketing/newsletter emails: prefer actual unsubscribe/block URLs (no mailto fallbacks).
                # Use the same context used for rendering, so header links match the email body.
                unsubscribe_url = render_context.get("unsubscribe_url")
                if unsubscribe_url:
                    list_unsubscribe_urls.append(unsubscribe_url)

                block_list_url = render_context.get("block_list_url")
                if block_list_url:
                    list_unsubscribe_urls.append(block_list_url)

                if not list_unsubscribe_urls:
                    logger.warning(
                        "No unsubscribe_url or block_list_url available for non-transactional email; "
                        "omitting List-Unsubscribe headers."
                    )
            
            # Prepare email headers - only include List-Unsubscribe if we have a valid URL
            # Note: X-Mailer cannot be set via Headers collection in Mailjet API (error send-0011)
            # Mailjet sets this automatically, so we omit it
            email_headers = {
                # Precedence header indicates transactional email
                "Precedence": "bulk",
                # Auto-Submitted header indicates automated email
                "Auto-Submitted": "auto-generated"
            }
            
            # Add List-Unsubscribe header(s).
            # RFC 2369 allows multiple URLs separated by commas; RFC 8058 one-click applies to HTTP(S).
            if list_unsubscribe_urls:
                unique_urls: list[str] = []
                for url in list_unsubscribe_urls:
                    if url and url not in unique_urls:
                        unique_urls.append(url)
                email_headers["List-Unsubscribe"] = ", ".join(f"<{url}>" for url in unique_urls)

                has_http_unsubscribe = False
                for url in unique_urls:
                    try:
                        scheme = urlparse(url).scheme.lower()
                    except Exception:
                        scheme = ""
                    if scheme in ("http", "https"):
                        has_http_unsubscribe = True
                        break
                if has_http_unsubscribe:
                    email_headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            
            # Return the original log message - filter will redact the email
            log_message = f"Sending email to {recipient_email} using template {template} in language {lang}"
            if attachments:
                log_message += f" with {len(attachments)} attachment(s)"
            logger.info(log_message)
            
            # Log the exact time we're attempting to send (to diagnose 1AM issue)
            from datetime import datetime, timezone
            send_attempt_time = datetime.now(timezone.utc)
            logger.info(f"[EMAIL_SEND_TIMING] Attempting to send email at {send_attempt_time.isoformat()} UTC")
            
            # Create provider instances and send email
            if use_brevo:
                if not self._brevo_provider or self._brevo_provider.api_key != brevo_api_key:
                    self._brevo_provider = BrevoProvider(api_key=brevo_api_key)
                
                result = await self._brevo_provider.send_email(
                    sender_name=sender_name,
                    sender_email=sender_email,
                    recipient_email=recipient_email,
                    recipient_name=recipient_name,
                    subject=subject,
                    html_content=html_content,
                    plain_text_content=plain_text_content,
                    email_headers=email_headers,
                    attachments=attachments
                )
                return result
            elif use_mailjet:
                if (not self._mailjet_provider or 
                    self._mailjet_provider.api_key != mailjet_api_key or 
                    self._mailjet_provider.api_secret != mailjet_api_secret):
                    self._mailjet_provider = MailjetProvider(
                        api_key=mailjet_api_key,
                        api_secret=mailjet_api_secret
                    )
                
                result = await self._mailjet_provider.send_email(
                    sender_name=sender_name,
                    sender_email=sender_email,
                    recipient_email=recipient_email,
                    recipient_name=recipient_name,
                    subject=subject,
                    html_content=html_content,
                    plain_text_content=plain_text_content,
                    email_headers=email_headers,
                    attachments=attachments
                )
                
                # Schedule Mailjet contact cleanup if email was sent successfully
                if result:
                    self._mailjet_provider.schedule_contact_cleanup(recipient_email)
                
                return result
            else:
                logger.error("No email provider selected - this should not happen")
                return False
                        
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}", exc_info=True)
            return False
    
    def clear_cache(self) -> None:
        """Clear the image cache"""
        image_cache.clear()
