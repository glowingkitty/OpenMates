"""
Shared dependencies for authentication routes.
This file contains functions that provide services to all auth-related endpoints.
"""
import logging

logger = logging.getLogger(__name__)

def get_directus_service():
    """Get the Directus service instance from main application."""
    from main import directus_service
    return directus_service

def get_cache_service():
    """Get the Cache service instance from main application."""
    from main import cache_service
    return cache_service

def get_metrics_service():
    """Get the Metrics service instance from main application."""
    from main import metrics_service
    return metrics_service

def get_compliance_service():
    """Get the Compliance service instance."""
    from app.services.compliance import ComplianceService
    return ComplianceService()

def get_email_template_service():
    """Get the Email Template service instance."""
    from app.services.email_template import EmailTemplateService
    return EmailTemplateService()
