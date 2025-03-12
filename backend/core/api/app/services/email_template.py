import os
import logging
from typing import Dict, Any
# Fix the import to use the correct function from python-mjml
from mjml import mjml2html
from jinja2 import Template, Environment, FileSystemLoader

from app.services.translations import TranslationService

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
        
        # Initialize Jinja environment
        self.env = Environment(loader=FileSystemLoader(self.templates_dir))
        
        # Initialize translation service
        self.translation_service = TranslationService()
        
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
            # Load template file
            template_path = f"{template_name}.mjml"
            with open(os.path.join(self.templates_dir, template_path), 'r') as f:
                mjml_template = f.read()
            
            # Load translations
            translations = self.translation_service.get_translations(lang)
            
            # Add translations to context
            context['t'] = translations
            
            # First render the template with Jinja to replace variables
            jinja_template = Template(mjml_template)
            rendered_mjml = jinja_template.render(**context)
            
            # Then convert MJML to HTML using the correct function from python-mjml
            html_output = mjml2html(rendered_mjml)
            
            return html_output
            
        except Exception as e:
            logger.error(f"Error rendering email template '{template_name}': {str(e)}")
            raise
