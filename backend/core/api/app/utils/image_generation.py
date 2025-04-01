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
        corner_radius = 30 * scale_factor # User requested 30px radius (scaled)
        final_w, final_h = 300 * scale_factor, 200 * scale_factor # Overall image size
        map_w, map_h = 300 * scale_factor, 150 * scale_factor # Map size remains same proportion

        # Text Box: 60px height (scaled), full width, bottom aligned with map
        box_h = 60 * scale_factor
        box_w = final_w # Full width
        box_x = 0 # Align left
        box_y = map_h - box_h # Align bottom with map bottom
        box_radius = corner_radius # Use the defined corner radius

        # Icon: 60x60 (scaled), left of text, vertically centered with text box
        icon_diameter = 60 * scale_factor
        icon_pin_size = 36 * scale_factor # Proportionally scale pin size (was 24 for 40 diameter)
        box_padding = 10 * scale_factor # Padding between elements
        icon_center_x = box_padding + icon_diameter // 2
        icon_center_y = box_y + box_h // 2 # Vertically center with text box

        shadow_offset = 2 * scale_factor # Keep shadow subtle
        shadow_blur_radius = 3 * scale_factor
        shadow_color = (50, 50, 50, 100) # Keep shadow subtle

        box_bg_color = (40, 40, 40) if darkmode else (255, 255, 255)
        box_border_color = (68, 68, 68) if darkmode else (229, 229, 229) # Keep for now, remove later
        text_color_main = (230, 230, 230) if darkmode else (20, 20, 20)
        text_color_secondary = (160, 160, 160) if darkmode else (100, 100, 100)
        gradient_start = "#11672D"
        gradient_end = "#3EAB61"

        font_path_regular = find_font("LexendDeca-Regular.ttf")
        font_path_bold = find_font("LexendDeca-Bold.ttf")
        font_size = 14 * scale_factor
        # Use default font size if specific font not found
        font_regular = ImageFont.truetype(font_path_regular, font_size) if font_path_regular else ImageFont.load_default(size=font_size)
        font_bold = ImageFont.truetype(font_path_bold, font_size) if font_path_bold else ImageFont.load_default(size=font_size)

        # --- Load i18n Text using TranslationService ---
        translation_service = TranslationService()
        # Get the specific text, remove potential <br> tag
        text_line1 = translation_service.get_nested_translation('email.area_around.text', lang='en').split("<br>")[0]


        # --- 1. Generate Base Map ---
        # Use a higher zoom level for better detail at higher resolution
        m = StaticMap(map_w, map_h, url_template='https://tile.openstreetmap.org/{z}/{x}/{y}.png')
        # Increased zoom level for better detail
        base_map_image = m.render(zoom=6, center=(longitude, latitude)).convert("RGBA")

        # --- 2. Create Final Canvas ---
        # Ensure canvas accommodates potential overflow from shadow/blur
        # Make canvas slightly larger to accommodate blur radius fully
        canvas_w = final_w + shadow_offset + shadow_blur_radius * 2
        canvas_h = final_h + shadow_offset + shadow_blur_radius * 2
        canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        # Offset for drawing onto the larger canvas (to fit blur)
        draw_offset_x = shadow_blur_radius
        draw_offset_y = shadow_blur_radius


        # --- 3. Draw Map Drop Shadow ---
        # Shadow is rectangular, applied before the rounded map
        shadow_layer = Image.new('RGBA', canvas.size, (0,0,0,0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        # Shadow for the map rectangle itself, no rounding, apply offset
        shadow_draw.rectangle(
            (draw_offset_x + shadow_offset, draw_offset_y + shadow_offset,
             draw_offset_x + map_w + shadow_offset, draw_offset_y + map_h + shadow_offset),
            fill=shadow_color
        )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_blur_radius))
        # Composite shadow onto the main canvas first
        canvas = Image.alpha_composite(canvas, shadow_layer)


        # --- 4. Paste Base Map (over the shadow, with rounding) ---
        # Create rounded mask for the map itself
        map_mask = create_rounded_rectangle_mask((map_w, map_h), corner_radius)
        # Paste map with offset, using the rounded mask
        canvas.paste(base_map_image, (draw_offset_x, draw_offset_y), map_mask)


        # --- 5. Draw Text Box (Full Width, Bottom Aligned, Rounded) ---
        box_layer = Image.new('RGBA', (box_w, box_h), (0,0,0,0))
        box_draw = ImageDraw.Draw(box_layer)
        # Draw the rounded rectangle text box
        box_draw.rounded_rectangle((0, 0, box_w, box_h), radius=box_radius, fill=box_bg_color)
        # Create mask for pasting the box (using box_radius)
        box_mask = create_rounded_rectangle_mask((box_w, box_h), box_radius)
        # Paste box with offset, aligned to map bottom
        canvas.paste(box_layer, (draw_offset_x + box_x, draw_offset_y + box_y), box_mask)


        # --- 6. Draw Icon (Gradient Circle + Pin, Rounded) ---
        # Create gradient circle (already circular, no extra rounding needed unless we want rect)
        # If a rounded rectangle icon background is needed instead of circle:
        # icon_bg_mask = create_rounded_rectangle_mask((icon_diameter, icon_diameter), corner_radius)
        # gradient_rect = Image.new('RGBA', (icon_diameter, icon_diameter)) # Create gradient fill logic if needed
        # canvas.paste(gradient_rect, (paste_x, paste_y), icon_bg_mask)
        # For now, keeping the gradient circle as generated by create_gradient_circle
        gradient_circle = create_gradient_circle(icon_diameter, gradient_start, gradient_end)
        # Apply rounding mask to the gradient circle if needed (Pillow might clip automatically on paste)
        # circle_mask = create_rounded_rectangle_mask((icon_diameter, icon_diameter), corner_radius) # Use if pasting circle onto rect bg

        script_dir = os.path.dirname(__file__)
        icon_path = os.path.abspath(os.path.join(script_dir, '../../../../../frontend/packages/ui/static/icons/maps.png'))
        if os.path.exists(icon_path):
            map_pin_icon = Image.open(icon_path).convert("RGBA")
            map_pin_icon = map_pin_icon.resize((icon_pin_size, icon_pin_size), Image.Resampling.LANCZOS)

            # Calculate paste positions based on the icon's center, adjusting for draw offset
            circle_paste_x = int(draw_offset_x + icon_center_x - icon_diameter / 2)
            circle_paste_y = int(draw_offset_y + icon_center_y - icon_diameter / 2) # Center circle vertically with text box
            pin_x = int(draw_offset_x + icon_center_x - icon_pin_size / 2)
            pin_y = int(draw_offset_y + icon_center_y - icon_pin_size / 2) # Center pin vertically with text box

            # Paste circle first (using its own alpha for circular shape), then pin on top
            canvas.paste(gradient_circle, (circle_paste_x, circle_paste_y), gradient_circle)
            canvas.paste(map_pin_icon, (pin_x, pin_y), map_pin_icon)
        else:
            logger.warning(f"Map icon not found at {icon_path}")

        # --- 7. Render Text ---
        text_draw = ImageDraw.Draw(canvas)
        # text_line1 loaded via TranslationService
        text_line2 = f"{city}, {country}"
        text_padding_left = 15 * scale_factor # Space between icon and text start
        # Text starts after the icon + padding
        text_x_start = int(draw_offset_x + icon_center_x + icon_diameter / 2 + text_padding_left)
        line_spacing = 5 * scale_factor
        total_text_h = font_size * 2 + line_spacing
        # Center text vertically within the text box height, adjusting for draw offset
        text_y_start = draw_offset_y + box_y + (box_h - total_text_h) // 2

        # Use text anchor for better positioning relative to the start point
        text_draw.text((text_x_start, text_y_start), text_line1, font=font_bold, fill=text_color_main, anchor="ls") # ls = left, baseline
        text_draw.text((text_x_start, text_y_start + font_size + line_spacing), text_line2, font=font_regular, fill=text_color_secondary, anchor="ls")


        # --- 8. Crop to Final Size & Encode ---
        # Crop the canvas to the desired final dimensions (final_w, final_h)
        # The crop box starts at the draw offset
        final_image = canvas.crop((draw_offset_x, draw_offset_y, draw_offset_x + final_w, draw_offset_y + final_h))

        buffer = io.BytesIO()
        # Increase compression level (0=none, 9=max)
        final_image.save(buffer, format='PNG', optimize=True, compress_level=9)
        image_bytes = buffer.getvalue()

        encoded_string = base64.b64encode(image_bytes).decode('utf-8')
        data_uri = f"data:image/png;base64,{encoded_string}"
        logger.info(f"Successfully generated and encoded combined map preview image.")
        return data_uri

    except Exception as exc:
         logger.error(f"Error generating combined map preview image: {exc}", exc_info=True)
         return None