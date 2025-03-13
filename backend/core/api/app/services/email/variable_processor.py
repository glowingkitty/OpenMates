import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def process_template_variables(context: Dict[Any, Any]) -> Dict[Any, Any]:
    """
    Process template variables and set appropriate defaults
    
    Args:
        context: Template context dictionary
        
    Returns:
        Updated context with default values set
    """
    # Create a copy of context to avoid modifying the original
    processed_context = context.copy()
    
    # Get support email from context
    support_email = processed_context.get('contact_email', 'support@openmates.org')
    
    # Set defaults for required variables if not provided
    if 'refund_link' not in processed_context or not processed_context['refund_link']:
        processed_context['refund_link'] = f"mailto:{support_email}?subject=Refund%20Request"
        logger.debug(f"Using default refund_link: {processed_context['refund_link']}")
        
    if 'mailto_link_report_email' not in processed_context or not processed_context['mailto_link_report_email']:
        processed_context['mailto_link_report_email'] = f"mailto:{support_email}?subject=Suspicious%20Email%20Report"
        logger.debug(f"Using default mailto_link_report_email: {processed_context['mailto_link_report_email']}")
    
    # Set optional variables to empty strings if not provided or None
    optional_vars = ['device', 'os_with_version', 'count', 'logout_link_delete_invite_codes']
    for var in optional_vars:
        if var not in processed_context or processed_context[var] is None:
            processed_context[var] = ''
            logger.debug(f"Setting empty value for optional variable: {var}")
            
    return processed_context
