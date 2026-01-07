"""
Image Processing Service

Handles image resizing, format conversion, and optimization.
Uses Pillow for image manipulation.

Key features:
- Resize images to max width/height while maintaining aspect ratio
- Convert to optimized formats (WebP, JPEG)
- Adjust JPEG quality for file size optimization
- Handle various input formats (PNG, JPEG, GIF, WebP, SVG passthrough)
"""

import logging
import io
from typing import Optional, Tuple
from dataclasses import dataclass

from PIL import Image

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class ImageDimensions:
    """Image dimensions with optional max constraints."""
    width: int
    height: int
    max_width: Optional[int] = None
    max_height: Optional[int] = None


class ImageService:
    """
    Service for processing and optimizing images.
    
    Handles resizing, format conversion, and quality optimization
    for cached images.
    """
    
    # Formats that should be passed through without processing
    # (e.g., SVG is vector and shouldn't be rasterized)
    PASSTHROUGH_FORMATS = {"image/svg+xml"}
    
    # Formats that support transparency (use PNG for output)
    TRANSPARENT_FORMATS = {"image/png", "image/gif", "image/webp"}
    
    def process_image(
        self,
        image_data: bytes,
        content_type: str,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        quality: Optional[int] = None,
        output_format: Optional[str] = None
    ) -> Tuple[bytes, str]:
        """
        Process an image with optional resizing and quality optimization.
        
        Args:
            image_data: Raw image bytes
            content_type: Original content type (e.g., "image/jpeg")
            max_width: Maximum width (None = no limit, uses config default if 0)
            max_height: Maximum height (None = no limit, uses config default if 0)
            quality: JPEG/WebP quality 1-100 (None = use config default)
            output_format: Force output format ("jpeg", "png", "webp", None = auto)
            
        Returns:
            Tuple of (processed_image_bytes, output_content_type)
        """
        # Passthrough for SVG and other vector formats
        if content_type in self.PASSTHROUGH_FORMATS:
            logger.debug(f"[ImageService] Passthrough for {content_type}")
            return image_data, content_type
        
        # Use config defaults if not specified
        if max_width is None:
            max_width = settings.max_image_width if settings.max_image_width > 0 else None
        if max_height is None:
            max_height = settings.max_image_height if settings.max_image_height > 0 else None
        if quality is None:
            quality = settings.jpeg_quality
        
        # Explicit 0 means no limit
        if max_width == 0:
            max_width = None
        if max_height == 0:
            max_height = None
        
        try:
            # Open image with Pillow
            img = Image.open(io.BytesIO(image_data))
            original_format = img.format
            original_mode = img.mode
            original_size = img.size
            
            logger.debug(
                f"[ImageService] Processing image: {original_size[0]}x{original_size[1]}, "
                f"format={original_format}, mode={original_mode}"
            )
            
            # Check if resizing is needed
            needs_resize = False
            if max_width and img.width > max_width:
                needs_resize = True
            if max_height and img.height > max_height:
                needs_resize = True
            
            # Resize if needed (maintain aspect ratio)
            if needs_resize:
                img = self._resize_image(img, max_width, max_height)
                logger.debug(
                    f"[ImageService] Resized from {original_size[0]}x{original_size[1]} "
                    f"to {img.width}x{img.height}"
                )
            
            # Determine output format
            out_format, out_content_type = self._determine_output_format(
                img, content_type, original_format, output_format
            )
            
            # Convert and save
            output_data = self._save_image(img, out_format, quality)
            
            logger.debug(
                f"[ImageService] Output: {len(output_data)} bytes, "
                f"format={out_format}, type={out_content_type}"
            )
            
            return output_data, out_content_type
            
        except Exception as e:
            logger.error(f"[ImageService] Error processing image: {e}")
            # Return original on error
            return image_data, content_type
    
    def _resize_image(
        self,
        img: Image.Image,
        max_width: Optional[int],
        max_height: Optional[int]
    ) -> Image.Image:
        """
        Resize image to fit within max dimensions while maintaining aspect ratio.
        
        Uses LANCZOS resampling for high quality downscaling.
        
        Args:
            img: PIL Image object
            max_width: Maximum width constraint
            max_height: Maximum height constraint
            
        Returns:
            Resized PIL Image
        """
        original_width, original_height = img.size
        
        # Calculate new dimensions maintaining aspect ratio
        new_width = original_width
        new_height = original_height
        
        # Apply width constraint
        if max_width and new_width > max_width:
            ratio = max_width / new_width
            new_width = max_width
            new_height = int(new_height * ratio)
        
        # Apply height constraint
        if max_height and new_height > max_height:
            ratio = max_height / new_height
            new_height = max_height
            new_width = int(new_width * ratio)
        
        # Only resize if dimensions changed
        if new_width != original_width or new_height != original_height:
            # Use LANCZOS (high quality) resampling
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        return img
    
    def _determine_output_format(
        self,
        img: Image.Image,
        content_type: str,
        original_format: Optional[str],
        requested_format: Optional[str]
    ) -> Tuple[str, str]:
        """
        Determine the best output format for the image.
        
        ALWAYS uses WebP because:
        - WebP has excellent browser support (97%+ as of 2024)
        - WebP is 25-35% smaller than JPEG at same quality
        - WebP supports both lossy and lossless compression
        - WebP supports transparency (alpha channel)
        - Only unsupported in IE11 (deprecated) and very old Safari (pre-2020)
        
        The only exception is if a specific format is explicitly requested.
        
        Args:
            img: PIL Image object
            content_type: Original content type
            original_format: Original image format from Pillow
            requested_format: User-requested format (optional)
            
        Returns:
            Tuple of (pillow_format, content_type)
        """
        # If specific format requested, honor it
        if requested_format:
            format_map = {
                "jpeg": ("JPEG", "image/jpeg"),
                "jpg": ("JPEG", "image/jpeg"),
                "png": ("PNG", "image/png"),
                "webp": ("WEBP", "image/webp"),
                "gif": ("GIF", "image/gif"),
            }
            if requested_format.lower() in format_map:
                return format_map[requested_format.lower()]
        
        # ALWAYS use WebP - best compression, supports transparency, excellent browser support
        return ("WEBP", "image/webp")
    
    def _save_image(
        self,
        img: Image.Image,
        format: str,
        quality: int
    ) -> bytes:
        """
        Save image to bytes with specified format and quality.
        
        Args:
            img: PIL Image object
            format: Output format (JPEG, PNG, WEBP, GIF)
            quality: Quality level for lossy formats
            
        Returns:
            Image bytes
        """
        output = io.BytesIO()
        
        # Convert mode if necessary based on format
        if format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
            # JPEG doesn't support transparency - convert to RGB with white background
            if img.mode == "P":
                img = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "RGBA":
                background.paste(img, mask=img.split()[3])  # Use alpha as mask
            else:
                background.paste(img)
            img = background
        elif format == "JPEG" and img.mode != "RGB":
            img = img.convert("RGB")
        elif format == "WEBP":
            # WebP supports transparency - convert P mode to RGBA to preserve it
            if img.mode == "P":
                img = img.convert("RGBA")
            # For non-transparent images, convert to RGB for slightly better compression
            elif img.mode not in ("RGBA", "LA", "RGB"):
                img = img.convert("RGB")
        
        # Save with appropriate options
        save_kwargs = {}
        
        if format == "JPEG":
            save_kwargs = {
                "quality": quality,
                "optimize": True,
                "progressive": True,
            }
        elif format == "PNG":
            save_kwargs = {
                "optimize": True,
            }
        elif format == "WEBP":
            save_kwargs = {
                "quality": quality,
                "method": 4,  # Compression method (0-6, higher = slower but smaller)
                "lossless": False,  # Use lossy compression for better file size
            }
        
        img.save(output, format=format, **save_kwargs)
        return output.getvalue()
    
    def get_image_dimensions(self, image_data: bytes) -> Tuple[int, int]:
        """
        Get dimensions of an image without fully loading it.
        
        Args:
            image_data: Raw image bytes
            
        Returns:
            Tuple of (width, height)
        """
        img = Image.open(io.BytesIO(image_data))
        return img.size


# Global image service instance
image_service = ImageService()

