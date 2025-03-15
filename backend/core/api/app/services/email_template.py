import os
import logging
import re
import base64
import yaml
from typing import Dict, Any, Optional
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

from app.services.translations import TranslationService
from app.services.email.config_loader import load_shared_urls, add_shared_urls_to_context
from app.services.email.variable_processor import process_template_variables
from app.services.email.renderer import render_mjml_template
from app.services.email.mjml_processor import image_cache

# Configure cssutils logger to suppress email-specific CSS property warnings
cssutils.log.setLevel(logging.ERROR)  # Only show ERROR level messages from cssutils

logger = logging.getLogger(__name__)

class EmailTemplateService:
    """Service for rendering and sending email templates using Brevo API."""
    
    def __init__(self):
        """Initialize the email template service with template directory and Brevo API key."""
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
        
        # Get Brevo API key from environment
        self.brevo_api_key = os.getenv("BREVO_API_KEY")
        if not self.brevo_api_key:
            logger.warning("BREVO_API_KEY not set. Email sending will not work.")
            
        # Brevo API endpoint
        self.brevo_api_url = "https://api.brevo.com/v3/smtp/email"
        
        # Default sender info
        self.default_sender_name = os.getenv("EMAIL_SENDER_NAME", "OpenMates")
        self.default_sender_email = os.getenv("EMAIL_SENDER_EMAIL", "noreply@openmates.org")
        
        logger.info(f"Email template service initialized with templates directory: {self.templates_dir}")
    
    def render_template(
        self, 
        template_name: str,
        context: Dict[str, Any] = None,
        lang: str = "en"
    ) -> str:
        """
        Render an email template with the given context.
        
        Args:
            template_name: Name of the template to render
            context: Dictionary of variables to pass to the template
            lang: Language code for translations
            
        Returns:
            Rendered HTML content
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
        lang: str = "en"
    ) -> bool:
        """
        Send an email using the Brevo API with a rendered template.
        
        Args:
            template: Template name to use
            recipient_email: Email address of the recipient
            recipient_name: Name of the recipient (optional)
            context: Dictionary of variables for the template
            subject: Custom subject line (uses template default if None)
            sender_name: Name of sender (uses default if None)
            sender_email: Email of sender (uses default if None)
            lang: Language code for translations
            
        Returns:
            True if email was sent successfully, False otherwise
        """
        if not self.brevo_api_key:
            logger.error("Cannot send email: BREVO_API_KEY not set")
            return False
            
        try:
            # Initialize default context if needed
            if context is None:
                context = {}
                
            # Set defaults for sender
            sender_name = sender_name or self.default_sender_name
            sender_email = sender_email or self.default_sender_email
            
            # Get translations for the current language
            translations = self.translation_service.get_translations(lang, variables=context)
            
            # Get the subject from translations if not provided
            if not subject:
                if template == "confirm-email":
                    subject_key = "email.confirm_your_email.text"
                elif template == "purchase-confirmation":
                    subject_key = "email.purchase_confirmation.text"
                else:
                    subject_key = f"email.{template}.subject"
                
                # Try to get the translated subject
                subject = self.translation_service.get_nested_translation(subject_key, lang, context)
                if subject == subject_key:  # If key not found, use default
                    subject = f"Message from {self.default_sender_name}"
                
            # Add translations to context
            if 't' not in context:
                context['t'] = translations
                
            # Render the HTML template
            html_content = self.render_template(template, context, lang)
            
            # Prepare the email data for Brevo API
            email_data = {
                "sender": {
                    "name": sender_name,
                    "email": sender_email
                },
                "to": [
                    {
                        "email": recipient_email,
                        "name": recipient_name or recipient_email
                    }
                ],
                "subject": subject,
                "htmlContent": html_content
            }
            
            # Log that we're sending an email, but don't include sensitive context
            logger.info(f"Sending email to {recipient_email} using template {template} in language {lang}")
            
            # Send the email via Brevo API
            async with aiohttp.ClientSession() as session:
                headers = {
                    "api-key": self.brevo_api_key,
                    "content-type": "application/json",
                    "accept": "application/json"
                }
                
                async with session.post(
                    self.brevo_api_url,
                    headers=headers,
                    data=json.dumps(email_data)
                ) as response:
                    if response.status == 201:
                        response_data = await response.json()
                        logger.info(f"Email sent successfully. Message ID: {response_data.get('messageId')}")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to send email. Status: {response.status}, Response: {error_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}", exc_info=True)
            return False
    
    def clear_cache(self) -> None:
        """Clear the image cache"""
        image_cache.clear()
