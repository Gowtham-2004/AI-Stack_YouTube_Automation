"""Create a simple thumbnail image using Pillow."""

from __future__ import annotations

import logging
import textwrap

from PIL import Image, ImageDraw, ImageFont

from config.settings import Settings


LOGGER = logging.getLogger(__name__)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a truetype font when available and fall back to the default font."""
    for font_name in ("Arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def create_thumbnail(title_text: str, settings: Settings) -> str:
    """Generate a simple YouTube thumbnail with wrapped text overlay."""
    image = Image.new("RGB", (1280, 720), color=(14, 22, 38))
    draw = ImageDraw.Draw(image)

    draw.rectangle((40, 40, 1240, 680), outline=(80, 200, 120), width=8)
    draw.rectangle((70, 70, 1210, 650), fill=(27, 39, 63))

    title_font = _load_font(68)
    accent_font = _load_font(34)

    wrapped_title = textwrap.fill(title_text.strip(), width=20)
    draw.text((100, 120), "AI STACK AUTOMATION", font=accent_font, fill=(120, 220, 255))
    draw.text((100, 220), wrapped_title, font=title_font, fill=(255, 255, 255))
    draw.text((100, 580), "Automated with Python + AI", font=accent_font, fill=(124, 247, 165))

    image.save(settings.thumbnail_output_path)
    LOGGER.info("Thumbnail saved to %s", settings.thumbnail_output_path)
    return str(settings.thumbnail_output_path)
