import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

logger.setLevel(logging.DEBUG)

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
    
    # Determine if server is self-hosted based on server edition
    # This allows templates to conditionally load self-hosted or regular header/footer
    try:
        from backend.core.api.app.utils.server_mode import get_server_edition, get_hosting_domain
        server_edition = get_server_edition()
        # Set is_self_hosted to True if edition is "self_hosted", False otherwise
        processed_context['is_self_hosted'] = (server_edition == "self_hosted")
        logger.debug(f"Set is_self_hosted={processed_context['is_self_hosted']} based on server_edition={server_edition}")
        
        # Set header variables based on server edition
        # For self-hosted: header links to GitHub, for regular: use "#" as placeholder (no actual link)
        if processed_context['is_self_hosted']:
            # Set server edition text for display in header
            processed_context['server_edition_text'] = "Self-Hosted Edition"
            # Set header text and link URL for self-hosted
            processed_context['header_text'] = "OpenMates - Self-Hosted Edition"
            processed_context['header_link_url'] = "https://github.com/glowingkitty/OpenMates"
            logger.debug(f"Set header_text and header_link_url for self-hosted instance")
        else:
            # Regular header - use "#" as placeholder to avoid empty href
            processed_context['header_text'] = "OpenMates"
            processed_context['header_link_url'] = "#"
            logger.debug(f"Set header_text and header_link_url for regular instance")
    except Exception as e:
        # If we can't determine server edition, default to False (not self-hosted)
        # This ensures regular templates are used by default
        processed_context['is_self_hosted'] = False
        logger.warning(f"Could not determine server edition, defaulting is_self_hosted to False: {str(e)}")
    
    # Get support email from context
    support_email = processed_context.get('contact_email', 'support@openmates.org')
    
    # Set defaults for required variables if not provided
    # CRITICAL: Prioritize refund_deep_link_url over default mailto link
    # The purchase confirmation email generates a deep link URL that should be used instead of mailto
    # Check if refund_deep_link_url is available first (from purchase confirmation email)
    if 'refund_deep_link_url' in processed_context and processed_context.get('refund_deep_link_url'):
        # Use the deep link URL as refund_link
        processed_context['refund_link'] = processed_context['refund_deep_link_url']
        logger.debug(f"Using refund_deep_link_url as refund_link: {processed_context['refund_link'][:50]}...")
    elif 'refund_link' not in processed_context or not processed_context.get('refund_link'):
        # Fallback to mailto link only if deep link is not available and refund_link is not set
        processed_context['refund_link'] = f"mailto:{support_email}?subject=Refund%20Request"
        logger.debug(f"Using default mailto refund_link: {processed_context['refund_link']}")
        
    if 'mailto_link_report_email' not in processed_context or not processed_context['mailto_link_report_email']:
        processed_context['mailto_link_report_email'] = f"mailto:{support_email}?subject=Suspicious%20Email%20Report"
        logger.debug(f"Using default mailto_link_report_email: {processed_context['mailto_link_report_email']}")
    
    # Set block list URL for users to submit their email to be blocked
    # This replaces the mailto link in "did_not_request_email" translation
    # The URL points to a server-specific endpoint where users can block their email
    if 'block_list_url' not in processed_context or not processed_context.get('block_list_url'):
        # Try to get webapp URL from shared URLs (if available in context)
        # The add_shared_urls_to_context function may have set base URLs
        try:
            from backend.core.api.app.utils.server_mode import get_hosting_domain
            
            # Determine environment
            is_prod = processed_context.get('is_production', True)
            
            # Construct block list URL from hosting domain
            # This creates a server-specific URL pointing to the block list endpoint
            hosting_domain = get_hosting_domain()
            
            if hosting_domain:
                # Use HTTPS by default for production, HTTP for development
                protocol = "https" if is_prod else "http"
                base_url = f"{protocol}://{hosting_domain}/block-email"
            else:
                # Fallback to localhost for development
                base_url = "http://localhost:5174/block-email"
            
            # Append email to URL hash if available in context
            # Check for common email field names in context
            # Ensure we get a string value, not a dict or other object
            email_address = None
            for key in ['account_email', 'recipient_email', 'email']:
                value = processed_context.get(key)
                # Only use if it's a string and not empty
                if value and isinstance(value, str):
                    email_address = value
                    break
            
            if email_address:
                # URL encode the email for the hash parameter
                from urllib.parse import quote
                encoded_email = quote(email_address)
                processed_context['block_list_url'] = f"{base_url}#email={encoded_email}"
            else:
                # Use default email for preview/development purposes if no email provided
                # This ensures blocklist links work even in preview mode
                default_email = "preview@example.com"
                from urllib.parse import quote
                encoded_email = quote(default_email)
                processed_context['block_list_url'] = f"{base_url}#email={encoded_email}"
                logger.debug(f"No email found in context, using default email for blocklist URL: {default_email}")
            
            logger.debug(f"Set block_list_url={processed_context['block_list_url']}")
        except Exception as e:
            # If we can't determine the URL, use a fallback
            processed_context['block_list_url'] = "https://openmates.org/block-email"
            logger.warning(f"Could not determine block_list_url, using fallback: {str(e)}")
    
    # Set server_domain variable for use in email templates
    # This allows templates to display the actual server domain instead of hardcoded "openmates.org"
    if 'server_domain' not in processed_context or not processed_context.get('server_domain'):
        try:
            from backend.core.api.app.utils.server_mode import get_hosting_domain
            hosting_domain = get_hosting_domain()
            if hosting_domain:
                processed_context['server_domain'] = hosting_domain
            else:
                # Fallback to openmates.org if no domain is detected (localhost/development)
                processed_context['server_domain'] = "openmates.org"
            logger.debug(f"Set server_domain={processed_context['server_domain']}")
        except Exception as e:
            # If we can't determine the domain, use fallback
            processed_context['server_domain'] = "openmates.org"
            logger.warning(f"Could not determine server_domain, using fallback: {str(e)}")
    
    # Process on_domain_text for confirm-email template
    # This replaces hardcoded "openmates.org" with the actual server domain in the translation
    # Must be done in Python, not in MJML template, to avoid breaking MJML parsing
    if 'on_domain_text' not in processed_context:
        # Check if translations are already loaded (they might be loaded after this function)
        # If not available, we'll process it later in email_template.py
        if 't' in processed_context and hasattr(processed_context['t'], 'get'):
            try:
                on_openmates_text = processed_context['t'].get('email', {}).get('on_openmates', {}).get('text', '')
                if on_openmates_text:
                    server_domain = processed_context.get('server_domain', 'openmates.org')
                    if server_domain != "openmates.org":
                        # Replace hardcoded domain with dynamic server domain
                        # Preserves language-specific prepositions and link positions
                        on_openmates_text = on_openmates_text.replace("https://openmates.org", f"https://{server_domain}")
                        on_openmates_text = on_openmates_text.replace(">openmates.org<", f">{server_domain}<")
                        processed_context['on_domain_text'] = on_openmates_text
                        logger.debug(f"Processed on_domain_text with server_domain={server_domain}")
                    else:
                        processed_context['on_domain_text'] = on_openmates_text
                else:
                    # Fallback if translation not found
                    processed_context['on_domain_text'] = f"on <a href='https://{processed_context.get('server_domain', 'openmates.org')}'>{processed_context.get('server_domain', 'openmates.org')}</a>"
            except Exception as e:
                logger.warning(f"Error processing on_domain_text: {str(e)}, using fallback")
                processed_context['on_domain_text'] = f"on <a href='https://{processed_context.get('server_domain', 'openmates.org')}'>{processed_context.get('server_domain', 'openmates.org')}</a>"
        else:
            # Translations not loaded yet, will be processed in email_template.py
            # Set a flag so we know to process it later
            processed_context['_process_on_domain_text'] = True

    logger.debug(f"Processed context: {processed_context}")
    
    # Set social media URLs if not provided
    # TODO adding the urls in footer.mjml or here broke the email processing. Need to fix this later. For now removed the urls from email footer.
    # if 'instagram_url' not in processed_context or not processed_context['instagram_url']:
    #     processed_context['instagram_url'] = "https://instagram.com/openmates_official"
    #     logger.debug(f"Using default instagram_url: {processed_context['instagram_url']}")
        
    # if 'github_url' not in processed_context or not processed_context['github_url']:
    #     processed_context['github_url'] = "https://github.com/glowingkitty/OpenMates"
    #     logger.debug(f"Using default github_url: {processed_context['github_url']}")

    # if 'meetup_url' not in processed_context or not processed_context['meetup_url']:
    #     processed_context['meetup_url'] = "https://www.meetup.com/openmates-meetup-group/"
    #     logger.debug(f"Using default meetup_url: {processed_context['meetup_url']}")
        
    # if 'mastodon_url' not in processed_context or not processed_context['mastodon_url']:
    #     processed_context['mastodon_url'] = "https://mastodon.social/@OpenMates"
    #     logger.debug(f"Using default mastodon_url: {processed_context['mastodon_url']}")
    
    # if 'pixelfed_url' not in processed_context or not processed_context['pixelfed_url']:
    #     processed_context['pixelfed_url'] = "https://pixelfed.social/@OpenMates"
    #     logger.debug(f"Using default pixelfed_url: {processed_context['pixelfed_url']}")
    
    
    # Set optional variables to empty strings if not provided or None
    optional_vars = ['device', 'os_with_version', 'count', 'logout_link_delete_invite_codes']
    for var in optional_vars:
        if var not in processed_context or processed_context[var] is None:
            processed_context[var] = ''
            logger.debug(f"Setting empty value for optional variable: {var}")
            
    return processed_context
