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
    darkmode: bool = False,
    lang: str = "en"  # Add language parameter with default
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
        icon_pin_size = 26 * scale_factor # User requested 26px (scaled)

        # Text positioning relative to icon
        text_padding_left = 15 * scale_factor # Space between icon and text start
        line_spacing = 5 * scale_factor
        font_size = 16 * scale_factor

        # Shadow properties
        shadow_offset = 4 * scale_factor # Slightly larger offset for visibility
        shadow_blur_radius = 4 * scale_factor # Reduced blur radius
        shadow_color = (0, 0, 0, 70) # Darker, less transparent shadow

        # Colors
        text_bg_color = (40, 40, 40, 255) if darkmode else (255, 255, 255, 255) # Opaque background
        text_color_main = (230, 230, 230) if darkmode else (20, 20, 20)
        text_color_secondary = (160, 160, 160) if darkmode else (100, 100, 100)
        gradient_start = "#11672D" # Green circle gradient
        gradient_end = "#3EAB61" # Green circle gradient
        center_dot_color_hex = "#4867CD" # User requested color
        # Convert hex to RGBA tuple for Pillow
        try:
            center_dot_color = tuple(int(center_dot_color_hex.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) + (255,) # Add alpha
        except ValueError:
            logger.error(f"Invalid hex color for center dot: {center_dot_color_hex}. Using default red.")
            center_dot_color = (255, 0, 0, 255) # Fallback solid red
        center_dot_radius = 5 * scale_factor

        # --- Fonts ---
        font_path_bold = find_font("LexendDeca-Bold.ttf")
        # Use default font size if specific font not found
        font_bold = ImageFont.truetype(font_path_bold, font_size) if font_path_bold else ImageFont.load_default(size=font_size)

        # --- Load i18n Text ---
        translation_service = TranslationService()
        # Use the lang parameter here
        text_line1 = translation_service.get_nested_translation('email.area_around.text', lang=lang).split("<br>")[0]
        text_line2 = f"{city}, {country}"

        # --- 1. Generate Base Map ---
        logger.info(f"Rendering map at {map_w}x{map_h} with zoom=6")
        # Choose tile URL based on darkmode
        if darkmode:
            # CartoDB Dark Matter tiles (supports {s} for subdomains and {r} for retina)
            map_url_template = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
            logger.info("Using CartoDB Dark Matter map tiles.")
        else:
            # Default OpenStreetMap tiles
            map_url_template = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
            logger.info("Using OpenStreetMap map tiles.")

        m = StaticMap(map_w, map_h, url_template=map_url_template)
        # Add attribution if needed, e.g., m.add_attribution(...)
        base_map_image = m.render(zoom=6, center=(longitude, latitude)).convert("RGBA")

        # --- 2. Add Center Dot to Map ---
        map_draw = ImageDraw.Draw(base_map_image)
        center_x, center_y = map_w // 2, map_h // 2
        dot_bbox = (center_x - center_dot_radius, center_y - center_dot_radius,
                    center_x + center_dot_radius, center_y + center_dot_radius)
        # Use the correct color, no outline
        map_draw.ellipse(dot_bbox, fill=center_dot_color)
        logger.info(f"Added center dot at ({center_x}, {center_y}) with color {center_dot_color}")

        # --- 3. Draw Overlay Elements (Order: Text BG -> Circle -> Pin -> Text) ---

        # --- 3a. Draw Full-Width Text Background (on separate layer) ---
        text_bg_h = 60 * scale_factor # Fixed height
        text_bg_w = map_w # Full width
        text_bg_layer = Image.new('RGBA', (text_bg_w, text_bg_h), (0,0,0,0))
        text_bg_draw = ImageDraw.Draw(text_bg_layer)
        # Draw rounded rect at (0,0) relative to this layer
        text_bg_draw.rounded_rectangle(
            (0, 0, text_bg_w, text_bg_h),
            radius=corner_radius, # Match outer rounding
            fill=text_bg_color
        )
        # Composite the background layer onto the base map at the bottom position
        text_bg_paste_y = map_h - text_bg_h
        base_map_image.alpha_composite(text_bg_layer, (0, text_bg_paste_y))
        logger.info(f"Composited full-width text background at (0, {text_bg_paste_y}) size {text_bg_w}x{text_bg_h}")

        # --- 3b. Create and Paste Icon Circle ---
        gradient_circle = create_gradient_circle(icon_diameter, gradient_start, gradient_end)

        # Calculate circle paste position (bottom-left edge)
        circle_paste_x = 0 # Align to very left edge
        circle_paste_y = map_h - icon_diameter # Align to very bottom edge

        # Paste circle onto map (on top of text background layer)
        base_map_image.paste(gradient_circle, (circle_paste_x, circle_paste_y), gradient_circle)
        logger.info(f"Pasted green circle at ({circle_paste_x}, {circle_paste_y})")

        # --- 3c. Load and Paste Map Pin Icon ---
        script_dir = os.path.dirname(__file__)
        # Corrected path relative to this script's location
        icon_path = os.path.abspath(os.path.join(script_dir, '../../templates/email/components/icons/maps.png'))
        logger.info(f"Attempting to load map icon from: {icon_path}") # Log path before try
        map_pin_icon = None
        if os.path.exists(icon_path):
             logger.info(f"Icon file exists at: {icon_path}")
             try:
                 map_pin_icon = Image.open(icon_path).convert("RGBA")
                 logger.info(f"Icon loaded successfully. Original size: {map_pin_icon.size}")
                 map_pin_icon = map_pin_icon.resize((icon_pin_size, icon_pin_size), Image.Resampling.LANCZOS)
                 logger.info(f"Icon resized to: {map_pin_icon.size}")
             except Exception as e:
                  logger.error(f"Error loading or resizing map icon from {icon_path}: {e}", exc_info=True)
                  map_pin_icon = None # Ensure it's None on error
        else:
             logger.warning(f"Map icon file NOT FOUND at {icon_path}. Skipping icon paste.")


        # Calculate pin paste position to center it within the circle's position
        pin_paste_x = circle_paste_x + (icon_diameter - icon_pin_size) // 2
        pin_paste_y = circle_paste_y + (icon_diameter - icon_pin_size) // 2

        # Paste pin onto map (on top of circle)
        if map_pin_icon:
             # Use the icon's own alpha channel for transparency when pasting
             base_map_image.paste(map_pin_icon, (pin_paste_x, pin_paste_y), map_pin_icon)
             logger.info(f"Pasted map pin icon at ({pin_paste_x}, {pin_paste_y})")
        else:
             logger.warning("map_pin_icon is None, skipping paste.")

        # --- 3d. Draw Text ---
        # Calculate text starting position based on circle diameter and padding
        text_actual_x_start = icon_diameter + text_padding_left # Start after circle + padding

        # Calculate total text height for vertical centering
        total_text_h = font_size * 2 + line_spacing
        # Calculate the top Y coordinate where the text block should start for mathematical centering
        block_top_y = text_bg_paste_y + (text_bg_h - total_text_h) // 2
        # Add a larger manual offset downwards as requested (30px = 15 * scale_factor)
        vertical_offset = 12 * scale_factor
        text_actual_y_start = block_top_y + vertical_offset # Baseline for the first line

        # Calculate baseline for the second line
        line2_y_start = text_actual_y_start + font_size + line_spacing

        # Draw text onto map (on top of text background and circle), using left-baseline anchor with adjusted Y
        map_draw.text((text_actual_x_start, text_actual_y_start), text_line1, font=font_bold, fill=text_color_main, anchor="ls") # Use left-baseline anchor
        map_draw.text((text_actual_x_start, line2_y_start), text_line2, font=font_bold, fill=text_color_secondary, anchor="ls") # Use left-baseline anchor
        logger.info(f"Drew text left-aligned starting at x={text_actual_x_start}, baseline adjusted vertically starting at y={text_actual_y_start}")

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