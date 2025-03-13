import re
import logging

logger = logging.getLogger(__name__)

def process_brand_name(content: str, dark_mode: bool = False) -> str:
    """
    Replace all occurrences of "OpenMates" with a link containing appropriately styled "Open" and "Mates" parts.
    Uses special styling for occurrences within footer sections.
    
    Args:
        content: HTML content
        dark_mode: Whether dark mode is enabled
        
    Returns:
        Processed HTML content
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

def process_mark_tags(content: str) -> str:
    """
    Replace all mark tags with spans that have inline styling
    Use stronger styling to ensure background is removed
    
    Args:
        content: HTML content
        
    Returns:
        Processed HTML content
    """
    # Pattern to match <mark>content</mark>
    pattern = r'<mark>(.*?)<\/mark>'
    
    # Replace with a span that has the desired styling with !important to ensure it overrides browser defaults
    replacement = r'<span style="color: #4867CD !important; background-color: transparent !important; background: none !important;">\1</span>'
    
    # Perform the replacement
    processed_content = re.sub(pattern, replacement, content)
    
    return processed_content

def process_link_tags(content: str) -> str:
    """
    Add custom styling to all anchor tags
    
    Args:
        content: HTML content
        
    Returns:
        Processed HTML content
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
