import re
import datetime
from babel.dates import format_date

def sanitize_html_for_reportlab(text):
    """
    Sanitize HTML for ReportLab compatibility
    
    Args:
        text: HTML text to sanitize
        
    Returns:
        Sanitized text compatible with ReportLab
    """
    if not isinstance(text, str):
        return text
        
    # Fix common HTML issues
    text = text.replace("<br>", "<br/>")
    text = text.replace("<br{", "<br/>{")
    
    # Fix problematic nested link formatting
    # Remove any href attributes that aren't part of <a> tags
    text = re.sub(r'href=([\'"])(.*?)\1(?![^<]*>)', r'\2', text)
    
    # Handle unclosed tags to prevent parsing errors
    unclosed_pattern = r'<([a-zA-Z]+)(?![^<>]*>)'
    text = re.sub(unclosed_pattern, r'', text)
    
    return text

def replace_placeholders_safely(text, replacements):
    """
    Replace placeholders in text while respecting HTML structure
    
    Args:
        text: Original text with placeholders
        replacements: Dictionary of {placeholder: replacement_value}
        
    Returns:
        Text with placeholders replaced safely
    """
    if not isinstance(text, str):
        return text
        
    # First extract any links to avoid nesting issues
    link_pattern = r'<a\s+href=[\'"]([^\'"]*)[\'"]>(.*?)<\/a>'
    
    def replace_link_placeholders(match):
        href = match.group(1)
        link_text = match.group(2)
        
        # Replace any placeholders in the href
        for placeholder, value in replacements.items():
            if placeholder in href:
                href = href.replace(placeholder, value)
        
        # Return properly formatted link
        return f'<a href="{href}" color="#4867CD">{link_text}</a>'
    
    # First handle links to prevent nesting issues
    text = re.sub(link_pattern, replace_link_placeholders, text)
    
    # Now replace any remaining placeholders in text
    for placeholder, value in replacements.items():
        if placeholder in text:
            text = text.replace(placeholder, value)
            
    return text

def format_date_for_locale(date_str, lang='en'):
    """
    Format date based on locale
    
    Args:
        date_str: Date in string format (YYYY-MM-DD)
        lang: Language code for formatting
        
    Returns:
        Formatted date string according to locale
    """
    try:
        # Parse the date string into a datetime object
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        
        # Format the date according to the locale
        # Use format='long' to get the full month name with appropriate formatting per locale
        return format_date(date_obj, format='long', locale=lang)
    except Exception as e:
        # Log the error for debugging
        print(f"Date formatting error: {e}")
        # Return original string if formatting fails
        return date_str

def format_credits(credits):
    """Format credits with thousand separator (e.g., 1.000)"""
    return f"{credits:,}".replace(",", ".")

def format_link_safely(url, display_text=None):
    """
    Format a URL as a safe hyperlink for ReportLab
    
    Args:
        url: The URL to link to
        display_text: Optional text to display instead of the URL
        
    Returns:
        Properly formatted HTML link
    """
    if not display_text:
        display_text = url
    
    # Simple formatting without nesting tags for safety
    return f'<a href="{url}" color="#4867CD">{display_text}</a>'
