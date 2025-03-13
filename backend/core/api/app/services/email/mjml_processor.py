import os
import re
import base64
import logging
from typing import Dict

logger = logging.getLogger(__name__)

class ImageCache:
    def __init__(self, max_size: int = 50):
        self.cache = {}
        self.max_size = max_size
        self.hits = 0
    
    def get(self, key: str) -> str:
        """Get an item from cache"""
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        return None
    
    def set(self, key: str, value: str) -> None:
        """Add an item to cache with LRU eviction"""
        if len(self.cache) >= self.max_size:
            # Get first key (oldest) and remove it
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            logger.debug(f"Cache full, removed oldest entry: {oldest_key}")
        
        self.cache[key] = value

    def clear(self) -> None:
        """Clear the cache"""
        self.cache = {}
        logger.info("Image cache cleared")

# Global image cache instance
image_cache = ImageCache()

def process_includes(templates_dir: str, mjml_content: str) -> str:
    """
    Process all include tags in the MJML content
    
    Args:
        templates_dir: Directory containing templates
        mjml_content: MJML content to process
        
    Returns:
        Processed MJML content
    """
    # Process CSS includes
    mjml_content = process_css_includes(templates_dir, mjml_content)
    
    # Process MJML includes
    mjml_content = process_mjml_includes(templates_dir, mjml_content)
    
    return mjml_content

def process_css_includes(templates_dir: str, mjml_content: str) -> str:
    """
    Process mj-include tags for CSS files
    
    Args:
        templates_dir: Directory containing templates
        mjml_content: MJML content to process
        
    Returns:
        Processed MJML content
    """
    pattern = r'<mj-include\s+path="([^"]+)"\s+type="css"\s*/>'
    
    def replace_css_include(match):
        path = match.group(1)
        # Remove leading ./ if present
        if path.startswith('./'):
            path = path[2:]
        
        try:
            with open(os.path.join(templates_dir, path), 'r') as f:
                css_content = f.read()
                return f'<mj-style>{css_content}</mj-style>'
        except Exception as e:
            logger.error(f"Error including CSS file {path}: {str(e)}")
            return f"<!-- Error including CSS {path} -->"
    
    return re.sub(pattern, replace_css_include, mjml_content)

def process_mjml_includes(templates_dir: str, mjml_content: str) -> str:
    """
    Process mj-include tags for MJML files
    
    Args:
        templates_dir: Directory containing templates
        mjml_content: MJML content to process
        
    Returns:
        Processed MJML content
    """
    pattern = r'<mj-include\s+path="([^"]+)"\s*/>'
    
    def replace_mjml_include(match):
        path = match.group(1)
        # Remove leading ./ if present
        if path.startswith('./'):
            path = path[2:]
        
        try:
            with open(os.path.join(templates_dir, path), 'r') as f:
                mjml_include = f.read()
                return mjml_include
        except Exception as e:
            logger.error(f"Error including MJML file {path}: {str(e)}")
            return f"<!-- Error including MJML {path} -->"
    
    return re.sub(pattern, replace_mjml_include, mjml_content)

def embed_images(templates_dir: str, content: str) -> str:
    """
    Safely embed images as Base64 data URLs
    
    Args:
        templates_dir: Directory containing templates
        content: MJML content to process
        
    Returns:
        Processed MJML content
    """
    # Pattern to match mj-image tags with src attributes pointing to PNG files
    pattern = r'<mj-image([^>]*?)src="([^"]+\.png)"([^>]*?)(/?)>'
    
    # Log cache stats periodically
    if image_cache.hits > 0 and image_cache.hits % 10 == 0:
        logger.info(f"Image cache stats: {len(image_cache.cache)} cached images, {image_cache.hits} cache hits")
    
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
                full_path = os.path.join(templates_dir, 'components', image_path)
            else:
                # Path might be relative to templates directory
                full_path = os.path.join(templates_dir, image_path)
        else:
            full_path = image_path
        
        # Check if image is in cache
        cached_result = image_cache.get(full_path)
        if cached_result:
            return cached_result
        
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
                image_cache.set(full_path, replacement)
                return replacement
            
            # Convert to Base64
            base64_data = base64.b64encode(img_data).decode('utf-8')
            
            # Create a clean data URL
            data_url = f"data:image/png;base64,{base64_data}"
            
            # Create the replacement tag - ENSURE it's self-closing
            replacement = f'<mj-image{before_src}src="{data_url}"{after_src} />'
            
            # Cache the result
            image_cache.set(full_path, replacement)
            
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
