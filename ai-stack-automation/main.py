"""CLI entrypoint for the AI Stack Automation pipeline."""

from __future__ import annotations

import argparse
import logging
import sys

from config.settings import get_settings
from modules.script_generator import generate_script
from modules.thumbnail_generator import create_thumbnail
from modules.uploader import upload_video
from modules.video_creator import create_video
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
    return parser.parse_args()


def main() -> int:
    """Run the full topic-to-video pipeline."""
    settings = get_settings()
    args = parse_args()
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
