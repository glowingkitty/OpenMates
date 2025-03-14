import os
import yaml
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def load_shared_urls() -> Dict[str, Any]:
    """
    Load the shared URL configuration from YAML file
    
    Returns:
        Dictionary with URL configurations
    """
    # Simplified path that works with Docker volume mount
    shared_config_path = "/shared/config/urls.yml"
    
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

def add_shared_urls_to_context(context: Dict[Any, Any], shared_urls: Dict[str, Any]) -> Dict[Any, Any]:
    """
    Add shared URLs from the YAML file to the template context
    
    Args:
        context: Template context dictionary
        shared_urls: Shared URL configuration
        
    Returns:
        Updated context with URL information
    """
    # Create a copy of context to avoid modifying the original
    processed_context = context.copy()
    
    try:
        # Determine environment
        is_prod = processed_context.get('is_production', True)
        env_name = 'production' if is_prod else 'development'
        
        # Get base website URL
        base_website = shared_urls.get('urls', {}).get('base', {}).get('website', {}).get(env_name, '')
        
        # Fix double slashes: remove trailing slash from base_website if present
        if (base_website and base_website.endswith('/')):
            base_website = base_website[:-1]
            
        # Process legal URLs
        legal_urls = shared_urls.get('urls', {}).get('legal', {})
        
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
        processed_context['privacy_url'] = f"{base_website}{privacy_path}" if base_website and privacy_path else "https://openmates.org"
        processed_context['terms_url'] = f"{base_website}{terms_path}" if base_website and terms_path else "https://openmates.org"
        processed_context['imprint_url'] = f"{base_website}{imprint_path}" if base_website and imprint_path else "https://openmates.org"
        
        # Get contact URLs
        contact_urls = shared_urls.get('urls', {}).get('contact', {})
        processed_context['discord_url'] = contact_urls.get('discord', '') or "https://openmates.org"
        
        # Ensure we have a support email for use in template variables
        support_email = contact_urls.get('email', '') or "support@openmates.org"
        processed_context['contact_email'] = support_email
        logger.debug(f"Using support email: {support_email}")
        
    except Exception as e:
        logger.error(f"Error adding shared URLs to context: {str(e)}. Using fallback URL.")
        # Set all fallbacks to just the base URL
        processed_context['privacy_url'] = "https://openmates.org"
        processed_context['terms_url'] = "https://openmates.org" 
        processed_context['imprint_url'] = "https://openmates.org"
        processed_context['discord_url'] = "https://openmates.org"
        processed_context['contact_email'] = "support@openmates.org"
    
    return processed_context
