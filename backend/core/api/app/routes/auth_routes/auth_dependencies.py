"""
Shared dependencies for authentication routes.
This file contains functions that provide services to all auth-related endpoints.
"""
from fastapi import Request

# All functions now accept Request and fetch services from app.state

def get_directus_service(request: Request):
    """Get the Directus service instance from app state."""
    return request.app.state.directus_service

def get_cache_service(request: Request):
    """Get the Cache service instance from app state."""
    return request.app.state.cache_service

def get_metrics_service(request: Request):
    """Get the Metrics service instance from app state."""
    return request.app.state.metrics_service
    
def get_encryption_service(request: Request):
    """Get the Encryption service instance from app state."""
    return request.app.state.encryption_service

def get_compliance_service(request: Request):
    """Get the Compliance service instance from app state."""
    return request.app.state.compliance_service

def get_email_template_service(request: Request):
    """Get the Email Template service instance from app state."""
    return request.app.state.email_template_service
