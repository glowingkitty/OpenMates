# backend/core/api/app/utils/image_processing.py
#
# Image processing utilities for format conversion and thumbnail generation.
# Uses Pillow for high-performance image manipulation.

import logging
import io
from typing import Tuple, Dict
from PIL import Image

logger = logging.getLogger(__name__)

def process_image_for_storage(
    image_bytes: bytes,
    thumbnail_size: Tuple[int, int] = (600, 400),
    webp_quality: int = 80
) -> Dict[str, bytes]:
    """
    Process a raw image (PNG/JPEG) into multiple formats for storage:
    1. Original (preserved as-is)
    2. Full-size WEBP (for editing/fullscreen)
    3. Preview WEBP (scaled down for embeds)
    
    Args:
        image_bytes: The raw image bytes from the provider
        thumbnail_size: Max (width, height) for the preview
        webp_quality: Quality setting for WEBP conversion
        
    Returns:
        Dict containing:
        - 'original': bytes
        - 'full_webp': bytes
        - 'preview_webp': bytes
    """
    results = {'original': image_bytes}
    
    try:
        # Load image from bytes
        img = Image.open(io.BytesIO(image_bytes))
        
        # 1. Generate Full-size WEBP
        full_webp_io = io.BytesIO()
        img.save(full_webp_io, format="WEBP", quality=webp_quality)
        results['full_webp'] = full_webp_io.getvalue()
        
        # 2. Generate Preview WEBP
        # Logic: 
        # - Horizontal/Square: 600x400 (crop to fit or letterbox)
        # - Vertical: 400px height, keep aspect ratio
        
        width, height = img.size
        is_vertical = height > width
        
        if is_vertical:
            # Vertical: fixed height 400, proportional width
            new_height = 400
            new_width = int(width * (new_height / height))
            preview_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        else:
            # Horizontal/Square: 600x400
            # We use thumbnail method which maintains aspect ratio but fits within bounds
            # Then we could crop if exact 600x400 is required, but usually 
            # fitting within bounds is better for not losing content.
            # User said: "600x400px image if its a horizontal or square shape image"
            
            # To get EXACTLY 600x400 for horizontal, we need to crop
            target_ratio = 600 / 400
            current_ratio = width / height
            
            if current_ratio > target_ratio:
                # Wider than target: crop sides
                new_width = int(height * target_ratio)
                left = (width - new_width) / 2
                img_cropped = img.crop((left, 0, left + new_width, height))
            else:
                # Taller than target: crop top/bottom
                new_height = int(width / target_ratio)
                top = (height - new_height) / 2
                img_cropped = img.crop((0, top, width, top + new_height))
                
            preview_img = img_cropped.resize((600, 400), Image.Resampling.LANCZOS)
            
        preview_webp_io = io.BytesIO()
        preview_img.save(preview_webp_io, format="WEBP", quality=webp_quality)
        results['preview_webp'] = preview_webp_io.getvalue()
        
        logger.info(f"Image processed successfully: original={len(image_bytes)}b, full_webp={len(results['full_webp'])}b, preview_webp={len(results['preview_webp'])}b")
        
    except Exception as e:
        logger.error(f"Failed to process image: {e}", exc_info=True)
        # If processing fails, we at least have the original
        if 'full_webp' not in results:
            results['full_webp'] = image_bytes
        if 'preview_webp' not in results:
            results['preview_webp'] = image_bytes
            
    return results
