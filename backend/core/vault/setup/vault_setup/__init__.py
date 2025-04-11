"""
Vault setup package for OpenMates.

This package provides modules for setting up and managing HashiCorp Vault.
"""

from .client import VaultClient
from .initialization import VaultInitializer
from .engines import SecretEngines
from .policies import PolicyManager
from .tokens import TokenManager
from .secrets import SecretsManager
from .utils import setup_logging

__all__ = [
    'VaultClient',
    'VaultInitializer',
    'SecretEngines',
    'PolicyManager',
    'TokenManager',
    'SecretsManager',
    'setup_logging'
]