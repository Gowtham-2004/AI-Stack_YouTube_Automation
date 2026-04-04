"""Application settings loaded from environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    """Store application configuration and resolved filesystem paths."""

    openai_api_key: str
    openai_model: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    youtube_client_secrets_file: str
    youtube_token_file: str
    youtube_category_id: str
    log_level: str
    base_dir: Path
    assets_dir: Path
    images_dir: Path
    videos_dir: Path
    audio_dir: Path
    output_dir: Path
    prompts_dir: Path
    script_prompt_path: Path
    script_output_path: Path
    voice_output_path: Path
    subtitles_output_path: Path
    final_video_path: Path
    thumbnail_output_path: Path


def _build_settings() -> Settings:
    """Create the settings object and ensure required directories exist."""
    assets_dir = BASE_DIR / "assets"
    images_dir = assets_dir / "images"
    videos_dir = assets_dir / "videos"
    audio_dir = assets_dir / "audio"
    output_dir = BASE_DIR / "output"
    prompts_dir = BASE_DIR / "prompts"

    for directory in (assets_dir, images_dir, videos_dir, audio_dir, output_dir, prompts_dir):
        directory.mkdir(parents=True, exist_ok=True)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL"),
        youtube_client_secrets_file=os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", ""),
        youtube_token_file=os.getenv("YOUTUBE_TOKEN_FILE", str(output_dir / "youtube_token.json")),
        youtube_category_id=os.getenv("YOUTUBE_CATEGORY_ID", "28"),
        log_level=log_level,
        base_dir=BASE_DIR,
        assets_dir=assets_dir,
        images_dir=images_dir,
        videos_dir=videos_dir,
        audio_dir=audio_dir,
        output_dir=output_dir,
        prompts_dir=prompts_dir,
        script_prompt_path=prompts_dir / "script_prompt.txt",
        script_output_path=output_dir / "script.txt",
        voice_output_path=audio_dir / "voice.mp3",
        subtitles_output_path=output_dir / "subtitles.srt",
        final_video_path=output_dir / "final_video.mp4",
        thumbnail_output_path=output_dir / "thumbnail.png",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings object for the current process."""
    return _build_settings()
