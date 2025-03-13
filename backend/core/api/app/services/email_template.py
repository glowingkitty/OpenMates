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

from app.services.translations import TranslationService

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
        
        # Initialize Jinja environment
        self.env = Environment(loader=FileSystemLoader(self.templates_dir))
        
        # Initialize translation service
        self.translation_service = TranslationService()
        
        # Initialize image cache
        self.image_cache = {}
        # Maximum cache size (number of images to store in memory)
        self.max_cache_size = 50
        # Cache hit counter for analytics
        self.cache_hits = 0
        
        # Load shared URL configuration
        self.shared_urls = self._load_shared_urls()
        
        logger.info(f"Email template service initialized with templates directory: {self.templates_dir}")
    
    def _load_shared_urls(self) -> Dict:
        """Load the shared URL configuration from YAML file"""
        shared_config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
            "shared", "config", "urls.yaml"
        )
        
        logger.info(f"Attempting to load shared URL config from: {shared_config_path}")
        
        try:
            # First check if file exists
            if not os.path.exists(shared_config_path):
                logger.error(f"Shared URL config file does not exist at {shared_config_path}")
                return {}
                
            # Try to open and parse the file
            with open(shared_config_path, 'r') as file:
                file_content = file.read()
                logger.debug(f"Raw YAML content:\n{file_content}")
                
                config = yaml.safe_load(file_content)
                
                # Basic validation
                if not isinstance(config, dict):
                    logger.error("Loaded YAML is not a dictionary")
                    return {}
                    
                if 'urls' not in config:
                    logger.error("YAML is missing 'urls' key")
                    return {}
                    
                logger.info(f"Successfully loaded shared URL configuration")
                return config
                
        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error: {str(e)}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error loading shared URL configuration: {str(e)}")
            return {}

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
            # Add shared URLs to context
            self._add_shared_urls_to_context(context)
            
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
            
            # Get dark mode setting from context
            dark_mode = context.get('darkmode', False)
            
            # Process brand name to add mark tags with appropriate styling
            rendered_mjml = self._process_brand_name(rendered_mjml, dark_mode)
            
            # Process any mark tags in the rendered content - make sure this works properly
            rendered_mjml = self._process_mark_tags(rendered_mjml)

            # Log the MJML before image embedding
            logger.debug(f"MJML content before image embedding (first 500 chars): {rendered_mjml[:500]}")
            
            # Use safer image embedding
            rendered_mjml = self._embed_images_safely(rendered_mjml)
            
            # Log just a portion of the result to avoid excessive logging
            logger.debug(f"MJML after image embedding (first 500 chars): {rendered_mjml[:500]}...")
            logger.debug(f"MJML after image embedding (last 500 chars): ...{rendered_mjml[-500:]}")
            
            # Convert to HTML
            try:
                # Add debug logging to show problematic sections
                logger.debug("Attempting to process MJML to HTML")
                html_output = mjml2html(rendered_mjml)
                logger.debug("Successfully processed MJML to HTML")
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
                        context_end = min(len(rendered_mjml), end_pos + 100)
                        
                        # Log the problematic region with more context
                        logger.error(f"Problematic MJML region (position {start_pos}-{end_pos}):")
                        logger.error(f"Content before: '{rendered_mjml[context_start:start_pos]}'")
                        logger.error(f"Problem token: '{rendered_mjml[start_pos:end_pos]}'")
                        logger.error(f"Content after: '{rendered_mjml[end_pos:context_end]}'")
                
                # Try using original image links instead
                logger.info("Falling back to original image links...")
                try:
                    # Use a different approach - instead of embedding, use HTTP URLs
                    jinja_template = Template(processed_mjml)
                    original_rendered = jinja_template.render(**context)
                    processed_original = self._process_brand_name(original_rendered, dark_mode)
                    processed_original = self._process_mark_tags(processed_original)
                    html_output = mjml2html(processed_original)
                    logger.info("Fallback to original image links successful!")
                except Exception as e2:
                    logger.error(f"All fallback attempts failed: {str(e2)}")
                    raise e
            
            # Process links to style them
            html_output = self._process_link_tags(html_output)
            
            # Convert CSS classes to inline styles for email compatibility
            inlined_html = transform(html_output)
            
            return inlined_html
            
        except Exception as e:
            logger.error(f"Error rendering email template '{template_name}': {str(e)}")
            raise
    
    def _add_shared_urls_to_context(self, context: Dict[Any, Any]) -> None:
        """Add shared URLs from the YAML file to the template context"""
        try:
            # Determine environment
            is_prod = context.get('is_production', True)
            env_name = 'production' if is_prod else 'development'
            
            # Get base website URL
            base_website = self.shared_urls.get('urls', {}).get('base', {}).get('website', {}).get(env_name, '')
            
            # Fix double slashes: remove trailing slash from base_website if present
            if base_website and base_website.endswith('/'):
                base_website = base_website[:-1]
                
            # Process legal URLs
            legal_urls = self.shared_urls.get('urls', {}).get('legal', {})
            
            # Process privacy URL - ensure path starts with slash
            privacy_path = legal_urls.get('privacy', '')
            if privacy_path and not privacy_path.startswith('/'):
                privacy_path = '/' + privacy_path
            
            # Process terms URL - ensure path starts with slash
            terms_path = legal_urls.get('terms', '')
            if terms_path and not terms_path.startswith('/'):
                terms_path = '/' + terms_path
            
            # Process imprint URL - ensure path starts with slash
            imprint_path = legal_urls.get('imprint', '')
            if imprint_path and not imprint_path.startswith('/'):
                imprint_path = '/' + imprint_path
            
            # Construct full URLs
            context['privacy_url'] = f"{base_website}{privacy_path}" if base_website and privacy_path else "https://openmates.org"
            context['terms_url'] = f"{base_website}{terms_path}" if base_website and terms_path else "https://openmates.org"
            context['imprint_url'] = f"{base_website}{imprint_path}" if base_website and imprint_path else "https://openmates.org"
            
            # Get contact URLs
            contact_urls = self.shared_urls.get('urls', {}).get('contact', {})
            context['discord_url'] = contact_urls.get('discord', '') or "https://openmates.org"
            context['contact_email'] = contact_urls.get('email', '') or "https://openmates.org"
            
        except Exception as e:
            logger.error(f"Error adding shared URLs to context: {str(e)}. Using fallback URL.")
            # Set all fallbacks to just the base URL
            context['privacy_url'] = "https://openmates.org"
            context['terms_url'] = "https://openmates.org" 
            context['imprint_url'] = "https://openmates.org"
            context['discord_url'] = "https://openmates.org"
            context['contact_email'] = "https://openmates.org"

    def _embed_images_safely(self, content: str) -> str:
        """
        A safer version of image embedding that handles problematic Base64 data
        Now with image caching
        """
        # Pattern to match mj-image tags with src attributes pointing to PNG files
        pattern = r'<mj-image([^>]*?)src="([^"]+\.png)"([^>]*?)(/?)>'
        
        # Log cache stats periodically
        if self.cache_hits > 0 and self.cache_hits % 10 == 0:
            logger.info(f"Image cache stats: {len(self.image_cache)} cached images, {self.cache_hits} cache hits")
        
        def replace_with_base64(match):
            before_src = match.group(1)
            image_path = match.group(2)
            after_src = match.group(3)
            
            # Remove leading slash if present
            if image_path.startswith('/'):
                image_path = image_path[1:]
            
            # Get full path to the image    
            if not os.path.isabs(image_path):
                if image_path.startswith('icons/'):
                    # Path is relative to components folder
                    full_path = os.path.join(self.templates_dir, 'components', image_path)
                else:
                    # Path might be relative to templates directory
                    full_path = os.path.join(self.templates_dir, image_path)
            else:
                full_path = image_path
            
            # Check if image is in cache
            if full_path in self.image_cache:
                self.cache_hits += 1
                return self.image_cache[full_path]
            
            try:
                # Read the image file
                with open(full_path, 'rb') as img_file:
                    img_data = img_file.read()
                    
                logger.debug(f"Reading image from {full_path}, size: {len(img_data)} bytes")
                
                # More conservative size limit - MJML parser has issues with very large Base64 strings
                if len(img_data) > 30000:  # 30KB limit
                    logger.warning(f"Image {image_path} is too large ({len(img_data)} bytes), skipping embedding")
                    # Return original tag with proper self-closing format
                    replacement = f'<mj-image{before_src}src="{image_path}"{after_src} />'
                    self._update_cache(full_path, replacement)
                    return replacement
                
                # Convert to Base64
                base64_data = base64.b64encode(img_data).decode('utf-8')
                
                # Create a clean data URL
                data_url = f"data:image/png;base64,{base64_data}"
                
                # Create the replacement tag - ENSURE it's self-closing
                replacement = f'<mj-image{before_src}src="{data_url}"{after_src} />'
                
                # Cache the result
                self._update_cache(full_path, replacement)
                
                return replacement
            except FileNotFoundError:
                logger.error(f"Image file not found: {full_path}")
                # Return a properly formatted tag even if file wasn't found
                replacement = f'<mj-image{before_src}src="{image_path}"{after_src} />'
                return replacement
            except Exception as e:
                logger.error(f"Error embedding image {image_path}: {str(e)}")
                # Return a properly formatted tag
                replacement = f'<mj-image{before_src}src="{image_path}"{after_src} />'
                return replacement
        
        # Replace all image references with Base64 data URLs
        result = re.sub(pattern, replace_with_base64, content)
        
        return result
    
    def _update_cache(self, key: str, value: str) -> None:
        """Update the image cache with LRU-like behavior"""
        # If cache is at max size, remove the oldest entry
        if len(self.image_cache) >= self.max_cache_size:
            # Get first key (oldest) and remove it
            oldest_key = next(iter(self.image_cache))
            del self.image_cache[oldest_key]
            logger.debug(f"Cache full, removed oldest entry: {oldest_key}")
        
        # Add new entry
        self.image_cache[key] = value
    
    def clear_cache(self) -> None:
        """Clear the image cache"""
        self.image_cache = {}
        logger.info("Image cache cleared")
        
    def _process_brand_name(self, content: str, dark_mode: bool = False) -> str:
        """
        Replace all occurrences of "OpenMates" with a link containing appropriately styled "Open" and "Mates" parts.
        Uses special styling for occurrences within footer sections.
        """
        # Determine the color for "Mates" based on dark mode for regular occurrences
        mates_color = "#e6e6e6" if dark_mode else "#000000"
        
        # First, handle OpenMates in footer sections with special colors
        footer_pattern = r'(<mj-section[^>]*css-class="footer"[^>]*>.*?)OpenMates(.*?</mj-section>)'
        footer_replacement = r'\1<a href="https://openmates.org" target="_blank" style="text-decoration: none;">' \
                            r'<span style="color: #FFFFFF;">Open</span><span style="color: #1C1C1C;">Mates</span></a>\2'
        
        # Replace "OpenMates" in footer sections with the special styling
        content = re.sub(footer_pattern, footer_replacement, content, flags=re.DOTALL)
        
        # Create regular replacement with inline styling for non-footer occurrences
        regular_replacement = f'<a href="https://openmates.org" target="_blank" style="text-decoration: none;">' \
                             f'<mark>Open</mark><span style="color: {mates_color};">Mates</span></a>'
        
        # Replace remaining "OpenMates" with our regular styled link
        content = content.replace("OpenMates", regular_replacement)
        
        return content
    
    def _process_mark_tags(self, content: str) -> str:
        """
        Replace all mark tags with spans that have inline styling
        Use stronger styling to ensure background is removed
        """
        # Pattern to match <mark>content</mark>
        pattern = r'<mark>(.*?)<\/mark>'
        
        # Replace with a span that has the desired styling with !important to ensure it overrides browser defaults
        replacement = r'<span style="color: #4867CD !important; background-color: transparent !important; background: none !important;">\1</span>'
        
        # Perform the replacement
        processed_content = re.sub(pattern, replacement, content)
        
        return processed_content
    
    def _process_link_tags(self, content: str) -> str:
        """
        Add custom styling to all anchor tags
        """
        # Pattern to match <a> tags
        pattern = r'<a\s+([^>]*?)>(.*?)<\/a>'
        
        def style_link(match):
            attrs = match.group(1)
            link_content = match.group(2)
            
            # Check if this is our brand link by looking for the "Open" in blue
            if 'style="color: #4867CD; background-color: unset;"' in link_content:
                # This is our brand link, don't add color to the entire link
                if 'style="' in attrs:
                    attrs = attrs.replace('style="', 'style="text-decoration: none; ')
                else:
                    attrs += ' style="text-decoration: none;"'
            else:
                # For regular links, apply blue color and no underline
                if 'style="' in attrs:
                    attrs = attrs.replace('style="', 'style="color: #4867CD; text-decoration: none; ')
                else:
                    attrs += ' style="color: #4867CD; text-decoration: none;"'
            
            return f'<a {attrs}>{link_content}</a>'
        
        # Perform the replacement
        processed_content = re.sub(pattern, style_link, content)
        
        return processed_content
            
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
