"""
S3 service module for handling file uploads and storage.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import S3UploadService


def __getattr__(name: str):
    if name == "S3UploadService":
        from .service import S3UploadService

        return S3UploadService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ['S3UploadService']
