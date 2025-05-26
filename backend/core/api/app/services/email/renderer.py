import os
import logging
import re
from typing import Dict, Any, Tuple
from mjml import mjml2html
from jinja2 import Template
from premailer import transform

from backend.core.api.app.services.email.mjml_processor import process_includes, embed_images
from backend.core.api.app.services.email.html_processor import process_brand_name, process_mark_tags, process_link_tags

logger = logging.getLogger(__name__)

def render_mjml_template(
    templates_dir: str,
    template_name: str,
    context: Dict[Any, Any]
) -> str:
    """
    Renders an MJML template to HTML
    
    Args:
        templates_dir: Directory containing templates
        template_name: Name of the template file (without extension)
        context: Dictionary of context variables
        
    Returns:
        Rendered HTML content
    """
    try:
        # Load template file
        template_path = f"{template_name}.mjml"
        with open(os.path.join(templates_dir, template_path), 'r') as f:
            mjml_template = f.read()
        
        # Process includes (CSS and MJML components)
        processed_mjml = process_includes(templates_dir, mjml_template)
        
        # Render with Jinja to handle template variables
        jinja_template = Template(processed_mjml)
        rendered_mjml = jinja_template.render(**context)
        
        # Get dark mode setting from context
        dark_mode = context.get('darkmode', False)
        
        # Process brand name to add mark tags with appropriate styling
        rendered_mjml = process_brand_name(rendered_mjml, dark_mode)
        
        # Process mark tags in the rendered content
        rendered_mjml = process_mark_tags(rendered_mjml)
        
        # Log the MJML before image embedding (first portion)
        logger.debug(f"MJML content before image embedding (first 500 chars): {rendered_mjml[:500]}")
        
        # Embed images as base64
        rendered_mjml = embed_images(templates_dir, rendered_mjml)
        
        # Convert to HTML with fallback handling
        html_output = convert_mjml_to_html(rendered_mjml, processed_mjml, context, dark_mode)
        
        # Process links to style them
        html_output = process_link_tags(html_output)
        
        # Convert CSS classes to inline styles for email compatibility
        inlined_html = transform(html_output)
        
        return inlined_html
        
    except FileNotFoundError as e:
        logger.error(f"Template file not found: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error rendering email template: {str(e)}")
        raise

def convert_mjml_to_html(
    mjml_content: str,
    original_mjml: str,
    context: Dict[Any, Any],
    dark_mode: bool
) -> str:
    """
    Convert MJML content to HTML with error handling and fallback
    
    Args:
        mjml_content: Processed MJML content with image embedding
        original_mjml: Original MJML content without image embedding (fallback)
        context: Template context variables
        dark_mode: Whether dark mode is enabled
        
    Returns:
        HTML output
    """
    try:
        # Try to convert with embedded images first
        logger.debug("Attempting to process MJML to HTML")
        html_output = mjml2html(mjml_content)
        logger.debug("Successfully processed MJML to HTML")
        return html_output
        
    except ValueError as e:
        error_msg = str(e)
        logger.error(f"MJML parsing error: {error_msg}")
        
        # Extract position information from error message if available
        if "position" in error_msg:
            pos_match = re.search(r'position (\d+)\.\.(\d+)', error_msg)
            if pos_match:
                start_pos = int(pos_match.group(1))
                end_pos = int(pos_match.group(2))
                
                # Log more context around the problematic area
                context_start = max(0, start_pos - 100)
                context_end = min(len(mjml_content), end_pos + 100)
                
                # Log the problematic region with more context
                logger.error(f"Problematic MJML region (position {start_pos}-{end_pos}):")
                logger.error(f"Content before: '{mjml_content[context_start:start_pos]}'")
                logger.error(f"Problem token: '{mjml_content[start_pos:end_pos]}'")
                logger.error(f"Content after: '{mjml_content[end_pos:context_end]}'")
        
        # Fallback: Try using original image links instead
        logger.info("Falling back to original image links...")
        try:
            # Use a different approach - instead of embedding, use HTTP URLs
            jinja_template = Template(original_mjml)
            original_rendered = jinja_template.render(**context)
            processed_original = process_brand_name(original_rendered, dark_mode)
            processed_original = process_mark_tags(processed_original)
            html_output = mjml2html(processed_original)
            logger.info("Fallback to original image links successful!")
            return html_output
        except Exception as e2:
            logger.error(f"All fallback attempts failed: {str(e2)}")
            raise e
