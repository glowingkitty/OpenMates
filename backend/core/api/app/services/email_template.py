import os
import logging
import re
import base64
import yaml
from typing import Dict, Any
from mjml import mjml2html
from jinja2 import Template, Environment, FileSystemLoader
from premailer import transform  # Add this import for CSS inlining
import cssutils  # Add this import to configure cssutils logger
import string

from app.services.translations import TranslationService
from app.services.email.config_loader import load_shared_urls, add_shared_urls_to_context
from app.services.email.variable_processor import process_template_variables
from app.services.email.renderer import render_mjml_template
from app.services.email.mjml_processor import image_cache

# Configure cssutils logger to suppress email-specific CSS property warnings
cssutils.log.setLevel(logging.ERROR)  # Only show ERROR level messages from cssutils

logger = logging.getLogger(__name__)

class EmailTemplateService:
    def __init__(self):
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
        
        logger.info(f"Email template service initialized with templates directory: {self.templates_dir}")
    
    def render_template(self, template_name: str, context: Dict[Any, Any], lang: str = "en") -> str:
        """
        Render an MJML email template with the given context and language
        
        Args:
            template_name: Name of the template file (without extension)
            context: Dictionary containing template variables
            lang: Language code for translations
            
        Returns:
            Rendered HTML string
        """
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
    
    def clear_cache(self) -> None:
        """Clear the image cache"""
        image_cache.clear()
