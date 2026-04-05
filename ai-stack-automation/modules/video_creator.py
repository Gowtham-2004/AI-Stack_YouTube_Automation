"""Build a video from narration audio and background media."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw

try:
    from moviepy import AudioFileClip, ImageClip, VideoFileClip
except ImportError:  # pragma: no cover
    from moviepy.editor import AudioFileClip, ImageClip, VideoFileClip

from config.settings import Settings


LOGGER = logging.getLogger(__name__)
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi"}


def _create_default_background(image_path: Path) -> Path:
    """Create a fallback background image when no media asset exists."""
    image = Image.new("RGB", (1920, 1080), color=(18, 24, 38))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 1840, 1000), outline=(74, 144, 226), width=8)
    draw.text((120, 120), "AI Stack Automation", fill=(255, 255, 255))
    draw.text((120, 220), "Automated video background placeholder", fill=(201, 214, 229))
    image.save(image_path)
    return image_path


def _find_background_media(settings: Settings) -> Path:
    """Select the first available background video or image from assets."""
    for file_path in sorted(settings.videos_dir.iterdir()):
        if file_path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            return file_path

    for file_path in sorted(settings.images_dir.iterdir()):
        if file_path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
            return file_path

    fallback_path = settings.images_dir / "default_background.png"
    return _create_default_background(fallback_path)


def _format_timestamp(seconds: float) -> str:
    """Convert seconds into SRT timestamp format."""
    total_milliseconds = int(seconds * 1000)
    hours = total_milliseconds // 3_600_000
    minutes = (total_milliseconds % 3_600_000) // 60_000
    secs = (total_milliseconds % 60_000) // 1000
    milliseconds = total_milliseconds % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def generate_subtitles(script_text: str, duration: float, settings: Settings) -> str:
    """Create a simple SRT file by distributing text evenly across sentences."""
    cleaned_sentences = [
        sentence.strip()
        for sentence in script_text.replace("\n", " ").split(".")
        if sentence.strip()
    ]
    if not cleaned_sentences:
        cleaned_sentences = [script_text.strip()]

    segment_duration = max(duration / max(len(cleaned_sentences), 1), 1.5)
    subtitle_lines = []

    current_start = 0.0
    for index, sentence in enumerate(cleaned_sentences, start=1):
        current_end = min(duration, current_start + segment_duration)
        subtitle_lines.extend(
            [
                str(index),
                f"{_format_timestamp(current_start)} --> {_format_timestamp(current_end)}",
                f"{sentence}.",
                "",
            ]
        )
        current_start = current_end

    settings.subtitles_output_path.write_text("\n".join(subtitle_lines), encoding="utf-8")
    LOGGER.info("Subtitles saved to %s", settings.subtitles_output_path)
    return str(settings.subtitles_output_path)


def create_test_video_from_image(
    image_path: str,
    settings: Settings,
    duration: float = 5.0,
) -> str:
    """Create a short silent MP4 from a still image for upload testing."""
    source_image = Path(image_path)
    if not source_image.exists():
        raise FileNotFoundError(f"Image file not found: {source_image}")

    if source_image.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported image file for test video: {source_image}")

    output_path = settings.output_dir / "upload_test_video.mp4"
    image_clip = None

    try:
        image_clip = ImageClip(str(source_image), duration=duration).resized((1920, 1080))
        image_clip.write_videofile(
            str(output_path),
            fps=24,
            codec="libx264",
            audio=False,
        )
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Test video creation failed.")
        raise RuntimeError(f"Failed to create test video from image: {exc}") from exc
    finally:
        if image_clip is not None:
            image_clip.close()

    LOGGER.info("Upload test video saved to %s", output_path)
    return str(output_path)


def create_video(script_text: str, audio_path: str, settings: Settings) -> str:
    """Combine narration with background media and export the final MP4 video."""
    audio_file = Path(audio_path)
    if not audio_file.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file}")

    background_media = _find_background_media(settings)
    LOGGER.info("Using background media: %s", background_media)

    audio_clip = AudioFileClip(str(audio_file))
    video_clip = None

    try:
        duration = audio_clip.duration
        if duration <= 0:
            raise RuntimeError("Generated audio has invalid duration.")

        if background_media.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            video_clip = VideoFileClip(str(background_media)).without_audio()
            if video_clip.duration < duration:
                video_clip = video_clip.loop(duration=duration)
            else:
                video_clip = video_clip.subclipped(0, duration)
            video_clip = video_clip.resized((1920, 1080))
        else:
            video_clip = ImageClip(str(background_media), duration=duration).resized((1920, 1080))

        final_clip = video_clip.with_audio(audio_clip)
        final_clip.write_videofile(
            str(settings.final_video_path),
            fps=24,
            codec="libx264",
            audio_codec="aac",
        )
        generate_subtitles(script_text=script_text, duration=duration, settings=settings)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Video creation failed.")
        raise RuntimeError(f"Failed to create video: {exc}") from exc
    finally:
        audio_clip.close()
        if video_clip is not None:
            video_clip.close()

    LOGGER.info("Final video saved to %s", settings.final_video_path)
    return str(settings.final_video_path)
