# backend/shared/python_utils/generated_assets/__init__.py
#
# Shared helpers for externally generated media assets.
# Long-running image, music, and video skills use this module to keep encrypted
# S3 storage, account storage indexing, cleanup metadata, and REST download
# links consistent across apps.

from .service import (
    GeneratedAssetVariant,
    build_download_url,
    cache_s3_file_keys,
    create_download_token,
    index_generated_asset,
    validate_download_token,
)

__all__ = [
    "GeneratedAssetVariant",
    "build_download_url",
    "cache_s3_file_keys",
    "create_download_token",
    "index_generated_asset",
    "validate_download_token",
]
