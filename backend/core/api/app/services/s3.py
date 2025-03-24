"""
S3 service module for handling file uploads and storage.

This module is maintained for backward compatibility.
The actual implementation has been moved to the s3/ directory.
"""
from .s3.service import S3UploadService

__all__ = ['S3UploadService']