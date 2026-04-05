"""CLI entrypoint for the AI Stack Automation pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config.settings import get_settings
from modules.script_generator import generate_script
from modules.thumbnail_generator import create_thumbnail
from modules.uploader import upload_video
from modules.video_creator import (
    SUPPORTED_IMAGE_EXTENSIONS,
    create_test_video_from_image,
    create_video,
)
from modules.voice_generator import generate_voice


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the automation pipeline."""
    parser = argparse.ArgumentParser(
        description="Generate and upload automated YouTube videos."
    )
    parser.add_argument(
        "topic",
        nargs="?",
        help="Topic for the YouTube video script.",
    )
    parser.add_argument(
        "--title",
        help="Optional custom title for the YouTube upload.",
    )
    parser.add_argument(
        "--description",
        default="AI-generated video created with AI Stack Automation.",
        help="Description used for the YouTube upload.",
    )
    parser.add_argument(
        "--tags",
        nargs="*",
        default=["AI", "Automation", "YouTube", "Python"],
        help="Tags used for the YouTube upload.",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Generate the video assets without uploading to YouTube.",
    )
    parser.add_argument(
        "--video-file",
        help="Upload an existing video file instead of generating a new one.",
    )
    parser.add_argument(
        "--thumbnail-file",
        help="Optional thumbnail file to use when uploading an existing video.",
    )
    return parser.parse_args()


def _resolve_cli_path(path_value: str | None) -> str | None:
    """Resolve an optional CLI path relative to the current working directory."""
    if not path_value:
        return None
    return str(Path(path_value).expanduser().resolve())


def main() -> int:
    """Run the full topic-to-video pipeline."""
    settings = get_settings()
    args = parse_args()
    existing_video = _resolve_cli_path(args.video_file)
    existing_thumbnail = _resolve_cli_path(args.thumbnail_file)

    if existing_video:
        title = args.title or "AI Stack Automation Upload Test"
        try:
            if Path(existing_video).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
                logging.info("Image provided for upload test. Creating a short MP4 first.")
                generated_test_video = create_test_video_from_image(
                    image_path=existing_video,
                    settings=settings,
                )
                existing_video = generated_test_video

            upload_response = upload_video(
                video_file=existing_video,
                title=title,
                description=args.description,
                tags=args.tags,
                thumbnail_file=existing_thumbnail,
                settings=settings,
            )
            logging.info("Upload complete: %s", upload_response.get("id"))
            return 0
        except Exception as exc:  # pylint: disable=broad-except
            logging.exception("Upload-only flow failed: %s", exc)
            return 1

    topic = args.topic or input("Enter a video topic: ").strip()

    if not topic:
        logging.error("A topic is required to generate a video.")
        return 1

    title = args.title or f"{topic.strip()} | AI Stack Automation"

    try:
        logging.info("Generating script for topic: %s", topic)
        script_text = generate_script(topic=topic, settings=settings)

        logging.info("Generating voice-over audio.")
        voice_path = generate_voice(script_text=script_text, settings=settings)

        logging.info("Creating video.")
        video_path = create_video(
            script_text=script_text,
            audio_path=voice_path,
            settings=settings,
        )

        logging.info("Creating thumbnail.")
        thumbnail_path = create_thumbnail(title_text=title, settings=settings)

        logging.info("Assets ready.")
        logging.info("Script: %s", settings.script_output_path)
        logging.info("Audio: %s", voice_path)
        logging.info("Video: %s", video_path)
        logging.info("Thumbnail: %s", thumbnail_path)

        if args.skip_upload:
            logging.info("Upload skipped by CLI flag.")
            return 0

        if not settings.youtube_client_secrets_file:
            logging.warning(
                "YouTube upload skipped because YOUTUBE_CLIENT_SECRETS_FILE is not configured."
            )
            return 0

        upload_response = upload_video(
            video_file=video_path,
            title=title,
            description=args.description,
            tags=args.tags,
            thumbnail_file=thumbnail_path,
            settings=settings,
        )
        logging.info("Upload complete: %s", upload_response.get("id"))
        return 0
    except Exception as exc:  # pylint: disable=broad-except
        logging.exception("Pipeline failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
