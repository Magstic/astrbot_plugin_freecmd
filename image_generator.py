# image_generator.py

import cv2
import freetype
import numpy as np
import os
import tempfile
import re
import io

# Global cache for font faces to avoid re-reading from disk
FONT_CACHE = {}

# Define base asset paths relative to this file's location
ASSETS_DIR = os.path.join(os.path.dirname(__file__), 'assets')
FONT_DIR = os.path.join(ASSETS_DIR, 'font')
TEMPLATE_DIR = os.path.join(ASSETS_DIR, 'templates')

def hex_to_bgr(hex_color):
    """Converts a hex color string to a BGR tuple."""
    hex_color = hex_color.lstrip('#')
    # Invert order for BGR
    return tuple(int(hex_color[i:i+2], 16) for i in (4, 2, 0))

def generate_image_with_text(text: str, options: dict) -> str:
    """
    Generates an image by drawing rich text on a template and saves it to a temporary file.

    Args:
        text: The text to draw, can contain markup like [color=...] and [size=...].
        options: A dictionary with image generation options.

    Returns:
        The path to the temporary image file, or None if an error occurs.
    """
    try:
        # 1. Construct full paths and validate
        template_path = os.path.join(TEMPLATE_DIR, options['template_name'])
        font_path = os.path.join(FONT_DIR, options['font_name'])

        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")
        if not os.path.exists(font_path):
            raise FileNotFoundError(f"Font not found: {font_path}")

        # 2. Load template image with OpenCV
        # Use np.fromfile and cv2.imdecode for safe loading from non-ASCII paths
        n = np.fromfile(template_path, dtype=np.uint8)
        image = cv2.imdecode(n, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise IOError(f"Failed to load template image: {template_path}")
        
        if len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

        # 3. Setup FreeType Face (with caching)
        if font_path in FONT_CACHE:
            face = FONT_CACHE[font_path]
        else:
            # Read the font file into memory and cache it to avoid re-reading
            with open(font_path, "rb") as f:
                font_bytes = f.read()
            face = freetype.Face(io.BytesIO(font_bytes))
            FONT_CACHE[font_path] = face
        pos_x, pos_y = options['position']

        # Get wrapping and spacing options
        max_width = options.get('max_width')
        line_spacing_multiplier = options.get('line_spacing', 1.2)

        # 4. Draw the rich text onto the image
        draw_text(image, text, (pos_x, pos_y), face, options,
                  max_width=max_width, line_spacing_multiplier=line_spacing_multiplier)

        # 5. Encode final image and save to a temporary file
        output_format = options.get('output_format', 'png').lower()
        if output_format not in ['png', 'webp', 'jpg', 'jpeg']:
            output_format = 'png'  # Default to png for unknown formats

        ext = f'.{output_format}'

        encode_params = []
        if output_format == 'webp':
            quality = options.get('quality', 90)
            encode_params = [cv2.IMWRITE_WEBP_QUALITY, quality]
        elif output_format in ['jpg', 'jpeg']:
            quality = options.get('quality', 95)
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]

        success, buffer = cv2.imencode(ext, image, encode_params)
        if not success:
            raise IOError(f"Failed to encode image to {output_format.upper()} format.")

        # Return the buffer and format directly, no temp file needed
        return buffer, output_format

    except Exception as e:
        print(f"[Image Generator] Error: {e}")
        return None, None

def _parse_rich_text(text, default_options):
    """Parses text with simple markup like [color=#...], [size=...], and [spacing=...] into styled segments."""
    segments = []
    # Add 'spacing' to the regex
    parts = re.split(r'(\[/?(?:color|size|spacing)[^\]]*\])', text)
    
    style_stack = [default_options.copy()]

    for part in parts:
        if not part:
            continue

        is_tag = part.startswith('[') and part.endswith(']')
        
        if is_tag:
            tag_content = part[1:-1]
            if tag_content.startswith('/'):  # Closing tag
                if len(style_stack) > 1:
                    style_stack.pop()
            else:  # Opening tag
                new_style = style_stack[-1].copy()
                try:
                    tag_type, value = tag_content.split('=', 1)
                    if tag_type == 'color':
                        new_style['color'] = value
                    elif tag_type == 'size':
                        new_style['font_size'] = int(value)
                    elif tag_type == 'spacing':
                        new_style['spacing'] = float(value)
                    style_stack.append(new_style)
                except ValueError:
                    # If tag is malformed, treat as plain text
                    segments.append({'text': part, 'style': style_stack[-1]})
        else:  # Plain text
            segments.append({'text': part, 'style': style_stack[-1]})
            
    return segments

def _draw_glyph(img, glyph_bitmap, x, y, color_bgr):
    """Draws a single glyph bitmap onto the target image with alpha blending."""
    w, h = glyph_bitmap.width, glyph_bitmap.rows
    if w == 0 or h == 0:
        return

    img_h, img_w = img.shape[:2]
    x_start_clip = max(0, -x)
    y_start_clip = max(0, -y)
    x_end_clip = max(0, x + w - img_w)
    y_end_clip = max(0, y + h - img_h)
    clipped_w = w - x_start_clip - x_end_clip
    clipped_h = h - y_start_clip - y_end_clip

    if clipped_w <= 0 or clipped_h <= 0:
        return

    target_roi = img[y + y_start_clip:y + y_start_clip + clipped_h, x + x_start_clip:x + x_start_clip + clipped_w]
    glyph_buffer = glyph_bitmap.buffer
    glyph_roi = np.array(glyph_buffer, dtype=np.uint8).reshape(h, w)[y_start_clip:y_start_clip + clipped_h, x_start_clip:x_start_clip + clipped_w]
    
    alpha = np.expand_dims(glyph_roi / 255.0, axis=2)
    
    blended_roi = (1.0 - alpha) * target_roi + alpha * color_bgr
    img[y + y_start_clip:y + y_start_clip + clipped_h, x + x_start_clip:x + x_start_clip + clipped_w] = blended_roi.astype(np.uint8)

def draw_text(img, text_to_draw, start_pos, face, base_options, max_width=None, line_spacing_multiplier=1.2):
    """Draws rich text with markup, clipping, and line wrapping."""
    default_style = {
        'color': base_options.get('color', '#000000'),
        'font_size': base_options.get('font_size', 40),
        'spacing': base_options.get('line_spacing', line_spacing_multiplier)
    }
    
    segments = _parse_rich_text(text_to_draw.replace('\\n', '\n'), default_style)

    x_start, y_start = start_pos
    pen_x, pen_y = x_start, y_start
    previous_char = 0
    
    for segment in segments:
        style = segment['style']
        text = segment['text']
        
        # Get style for the current segment
        current_font_size = style['font_size']
        current_spacing = style.get('spacing', default_style['spacing'])
        color_bgr = hex_to_bgr(style['color'])

        # Set face size for metrics
        face.set_pixel_sizes(0, current_font_size)
        ascender = face.size.ascender >> 6
        line_gap = int((face.size.height >> 6) * current_spacing)

        for char in text:
            if char == '\n':
                pen_x = x_start
                pen_y += line_gap
                previous_char = 0
                continue

            face.load_char(char, freetype.FT_LOAD_DEFAULT | freetype.FT_LOAD_RENDER)
            
            kerning = face.get_kerning(previous_char, char).x >> 6
            advance = face.glyph.advance.x >> 6
            
            if max_width and (pen_x + kerning + advance) > (x_start + max_width) and pen_x > x_start:
                pen_x = x_start
                pen_y += line_gap
                kerning = 0

            pen_x += kerning
            
            draw_x = pen_x + face.glyph.bitmap_left
            draw_y = pen_y + ascender - face.glyph.bitmap_top
            
            _draw_glyph(img, face.glyph.bitmap, draw_x, draw_y, color_bgr)
            
            pen_x += advance
            previous_char = char
