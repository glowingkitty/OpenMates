# backend/shared/providers/github/__init__.py
#
# Shared GitHub provider package.
# Pure API wrappers live here so apps, preview services, and core API routes can
# enrich GitHub repository URLs without duplicating provider-specific code.

from .repo_metadata import build_github_repo_embed, is_github_repo_url, parse_github_repo_url

__all__ = ["build_github_repo_embed", "is_github_repo_url", "parse_github_repo_url"]
