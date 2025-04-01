import logging
import os
import base64
import io
import math
# import json # No longer needed
from typing import Optional, Tuple

# Image manipulation libraries
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from staticmap import StaticMap # Keep staticmap here for base map generation

# Import the translation service
from app.services.translations import TranslationService

logger = logging.getLogger(__name__)

# --- Helper function to create rounded rectangle mask ---
def create_rounded_rectangle_mask(size: Tuple[int, int], radius: int) -> Image.Image:
    """Creates a mask (alpha channel) for a rounded rectangle."""
    width, height = size
    mask = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, width, height), radius=radius, fill=255)
    return mask

# --- Helper function for gradient ---
def create_gradient_circle(diameter: int, color_start_hex: str, color_end_hex: str) -> Image.Image:
    """Creates a circular image with a top-left to bottom-right diagonal gradient."""
    img = Image.new('RGBA', (diameter, diameter), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    try:
        r1, g1, b1 = tuple(int(color_start_hex.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
        r2, g2, b2 = tuple(int(color_end_hex.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    except ValueError:
        logger.error(f"Invalid hex color format: {color_start_hex} or {color_end_hex}")
        # Return a solid color circle as fallback? Or raise error? Returning transparent for now.
        return img 

    radius = diameter / 2.0
    center_x, center_y = radius, radius

    for x in range(diameter):
        for y in range(diameter):
            dx, dy = x - center_x, y - center_y
            if dx*dx + dy*dy <= radius*radius:
                norm_x = x / (diameter - 1) if diameter > 1 else 0.5
                norm_y = y / (diameter - 1) if diameter > 1 else 0.5
                t = (norm_x + norm_y) / 2.0
                
                r = int(r1 + (r2 - r1) * t)
                g = int(g1 + (g2 - g1) * t)
                b = int(b1 + (b2 - b1) * t)
                draw.point((x, y), fill=(r, g, b, 255))
                
    return img

# --- Helper function to find font file ---
def find_font(font_name: str) -> Optional[str]:
    """Attempts to find a font file in common locations."""
    script_dir = os.path.dirname(__file__)
    # Correct relative path to point to services/fonts/
    relative_font_path = os.path.abspath(os.path.join(script_dir, '../services/fonts'))

    search_paths = [
        relative_font_path,
        "/usr/share/fonts/truetype/lexend", # Example Linux path
        # Add more paths as needed
    ]
    for path in search_paths:
        try:
            font_path = os.path.join(path, font_name)
            if os.path.exists(font_path):
                logger.info(f"Found font at: {font_path}")
                return font_path
        except Exception as e:
            logger.debug(f"Error checking font path {path}: {e}")
            continue
    logger.warning(f"Font '{font_name}' not found in search paths: {search_paths}. Using default Pillow font.")
    return None

# --- Main Image Generation Function ---
def generate_combined_map_preview(
    latitude: float, 
    longitude: float, 
    city: str, 
    country: str, 
    darkmode: bool = False
) -> Optional[str]:
    """
    Generates the combined map preview image with map, icon, text box, and text.
    Returns a base64 encoded PNG data URI string, or None on error.
    """
    try:
        logger.info(f"Generating combined map preview image for ({latitude}, {longitude}) - Darkmode: {darkmode}")

        # --- Config (Doubled for 2x resolution & Layout Adjustments) ---
        scale_factor = 2
        # Core content dimensions (map + overlay) at 2x scale
        content_w, content_h = 300 * scale_factor, 200 * scale_factor
        map_w, map_h = content_w, content_h # Map takes the full content area initially
        corner_radius = 30 * scale_factor # User requested 30px radius (scaled)

        # Icon & Overlay Elements
        icon_diameter = 60 * scale_factor
        icon_pin_size = 36 * scale_factor # Proportionally scale pin size
        overlay_padding = 15 * scale_factor # Padding from bottom-left corner for overlay elements
        icon_center_x = overlay_padding + icon_diameter // 2
        icon_center_y = map_h - overlay_padding - icon_diameter // 2 # Relative to map bottom-left

        # Text positioning relative to icon
        text_padding_left = 15 * scale_factor # Space between icon and text start
        text_x_start = icon_center_x + icon_diameter // 2 + text_padding_left
        line_spacing = 5 * scale_factor
        font_size = 14 * scale_factor

        # Shadow properties
        shadow_offset = 4 * scale_factor # Slightly larger offset for visibility
        shadow_blur_radius = 6 * scale_factor # Slightly larger blur
        shadow_color = (0, 0, 0, 70) # Darker, less transparent shadow

        # Colors
        # box_bg_color = (40, 40, 40) if darkmode else (255, 255, 255) # No separate box needed
        text_color_main = (230, 230, 230) if darkmode else (20, 20, 20) # Keep text colors
        text_color_secondary = (160, 160, 160) if darkmode else (100, 100, 100)
        gradient_start = "#11672D" # Green circle gradient
        gradient_end = "#3EAB61" # Green circle gradient
        center_dot_color = (255, 0, 0, 200) # Red, slightly transparent dot
        center_dot_radius = 5 * scale_factor

        # --- Fonts ---
        font_path_regular = find_font("LexendDeca-Regular.ttf")
        font_path_bold = find_font("LexendDeca-Bold.ttf")
        # Use default font size if specific font not found
        font_regular = ImageFont.truetype(font_path_regular, font_size) if font_path_regular else ImageFont.load_default(size=font_size)
        font_bold = ImageFont.truetype(font_path_bold, font_size) if font_path_bold else ImageFont.load_default(size=font_size)

        # --- Load i18n Text ---
        translation_service = TranslationService()
        text_line1 = translation_service.get_nested_translation('email.area_around.text', lang='en').split("<br>")[0]
        text_line2 = f"{city}, {country}"

        # --- 1. Generate Base Map ---
        logger.info(f"Rendering map at {map_w}x{map_h} with zoom=6")
        m = StaticMap(map_w, map_h, url_template='https://tile.openstreetmap.org/{z}/{x}/{y}.png')
        base_map_image = m.render(zoom=6, center=(longitude, latitude)).convert("RGBA")

        # --- 2. Add Center Dot to Map ---
        map_draw = ImageDraw.Draw(base_map_image)
        center_x, center_y = map_w // 2, map_h // 2
        dot_bbox = (center_x - center_dot_radius, center_y - center_dot_radius,
                    center_x + center_dot_radius, center_y + center_dot_radius)
        map_draw.ellipse(dot_bbox, fill=center_dot_color, outline=(0,0,0,150), width=1*scale_factor) # Optional outline
        logger.info(f"Added center dot at ({center_x}, {center_y})")

        # --- 3. Create and Composite Overlay (Icon + Text) onto Map ---
        # Create gradient circle
        gradient_circle = create_gradient_circle(icon_diameter, gradient_start, gradient_end)

        # Load map pin icon
        script_dir = os.path.dirname(__file__)
        # Adjusted path assuming structure: backend/core/api/app/utils -> frontend/packages/ui/static/icons
        icon_path = os.path.abspath(os.path.join(script_dir, '../../../../../frontend/packages/ui/static/icons/maps.png'))
        map_pin_icon = None
        if os.path.exists(icon_path):
            map_pin_icon = Image.open(icon_path).convert("RGBA")
            map_pin_icon = map_pin_icon.resize((icon_pin_size, icon_pin_size), Image.Resampling.LANCZOS)
        else:
            logger.warning(f"Map icon not found at {icon_path}")

        # Calculate positions relative to map bottom-left
        circle_paste_x = int(icon_center_x - icon_diameter / 2)
        circle_paste_y = int(icon_center_y - icon_diameter / 2)
        pin_paste_x = int(icon_center_x - icon_pin_size / 2)
        pin_paste_y = int(icon_center_y - icon_pin_size / 2)

        # Paste circle onto map
        base_map_image.paste(gradient_circle, (circle_paste_x, circle_paste_y), gradient_circle)
        # Paste pin onto map (over circle)
        if map_pin_icon:
            base_map_image.paste(map_pin_icon, (pin_paste_x, pin_paste_y), map_pin_icon)

        # Draw text onto map
        total_text_h = font_size * 2 + line_spacing
        # Calculate text Y start to center vertically around icon's vertical center
        text_y_start = icon_center_y - total_text_h // 2
        map_draw.text((text_x_start, text_y_start), text_line1, font=font_bold, fill=text_color_main, anchor="ls")
        map_draw.text((text_x_start, text_y_start + font_size + line_spacing), text_line2, font=font_regular, fill=text_color_secondary, anchor="ls")
        logger.info("Composited overlay elements onto map")

        # --- 4. Create Final Canvas (Larger for Shadow) ---
        canvas_w = content_w + shadow_offset + shadow_blur_radius * 2
        canvas_h = content_h + shadow_offset + shadow_blur_radius * 2
        canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        # Offset for drawing the content onto the larger canvas
        draw_offset_x = shadow_blur_radius
        draw_offset_y = shadow_blur_radius

        # --- 5. Draw Drop Shadow ---
        shadow_layer = Image.new('RGBA', canvas.size, (0,0,0,0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        # Shadow for the rounded content rectangle
        shadow_draw.rounded_rectangle(
            (draw_offset_x + shadow_offset, draw_offset_y + shadow_offset,
             draw_offset_x + content_w + shadow_offset, draw_offset_y + content_h + shadow_offset),
            radius=corner_radius,
            fill=shadow_color
        )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_blur_radius))
        # Composite shadow onto the main canvas first
        canvas = Image.alpha_composite(canvas, shadow_layer)
        logger.info("Applied drop shadow")

        # --- 6. Paste Final Map (with overlay) onto Canvas with Rounding ---
        # Create rounded mask for the final content size
        content_mask = create_rounded_rectangle_mask((content_w, content_h), corner_radius)
        # Paste the map (which now includes the overlay) using the mask
        canvas.paste(base_map_image, (draw_offset_x, draw_offset_y), content_mask)
        logger.info("Pasted final rounded content onto canvas")

        # --- 7. Encode Final Image (Entire Canvas) ---
        buffer = io.BytesIO()
        # Use the canvas which includes the shadow
        canvas.save(buffer, format='PNG', optimize=True, compress_level=6) # Level 6 is good balance
        image_bytes = buffer.getvalue()

        encoded_string = base64.b64encode(image_bytes).decode('utf-8')
        data_uri = f"data:image/png;base64,{encoded_string}"
        logger.info(f"Successfully generated and encoded combined map preview image.")
        return data_uri

    except Exception as exc:
         logger.error(f"Error generating combined map preview image: {exc}", exc_info=True)
         return None