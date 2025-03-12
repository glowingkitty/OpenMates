import os
import logging
import re
from typing import Dict, Any
from mjml import mjml2html
from jinja2 import Template, Environment, FileSystemLoader
from premailer import transform  # Add this import for CSS inlining

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
            context['t'] = translations
            
            # First process includes (both CSS and MJML)
            processed_mjml = self._process_includes(mjml_template)
            
            # Then render with Jinja to handle template variables
            jinja_template = Template(processed_mjml)
            rendered_mjml = jinja_template.render(**context)
            
            # Convert to HTML
            html_output = mjml2html(rendered_mjml)
            
            # Convert CSS classes to inline styles for email compatibility
            inlined_html = transform(html_output)
            
            return inlined_html
            
        except Exception as e:
            logger.error(f"Error rendering email template '{template_name}': {str(e)}")
            raise
            
    def _process_includes(self, mjml_content: str) -> str:
        """
        Process all include tags in the MJML content
        """
        # Process CSS includes
        mjml_content = self._process_css_includes(mjml_content)
        
        # Process MJML includes
        mjml_content = self._process_mjml_includes(mjml_content)
        
        return mjml_content
    
    def _process_css_includes(self, mjml_content: str) -> str:
        """
        Process mj-include tags for CSS files
        """
        pattern = r'<mj-include\s+path="([^"]+)"\s+type="css"\s*/>'
        
        def replace_css_include(match):
            path = match.group(1)
            # Remove leading ./ if present
            if path.startswith('./'):
                path = path[2:]
            
            try:
                with open(os.path.join(self.templates_dir, path), 'r') as f:
                    css_content = f.read()
                    return f'<mj-style>{css_content}</mj-style>'
            except Exception as e:
                logger.error(f"Error including CSS file {path}: {str(e)}")
                return f"<!-- Error including CSS {path} -->"
        
        return re.sub(pattern, replace_css_include, mjml_content)
            
    def _process_mjml_includes(self, mjml_content: str) -> str:
        """
        Process mj-include tags for MJML files
        """
        pattern = r'<mj-include\s+path="([^"]+)"\s*/>'
        
        def replace_mjml_include(match):
            path = match.group(1)
            # Remove leading ./ if present
            if path.startswith('./'):
                path = path[2:]
            
            try:
                with open(os.path.join(self.templates_dir, path), 'r') as f:
                    mjml_include = f.read()
                    return mjml_include
            except Exception as e:
                logger.error(f"Error including MJML file {path}: {str(e)}")
                return f"<!-- Error including MJML {path} -->"
        
        return re.sub(pattern, replace_mjml_include, mjml_content)
