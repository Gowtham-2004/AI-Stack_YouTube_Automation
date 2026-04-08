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


def _resolve_env_path(value: str, default_path: Path | None = None) -> str:
    """Resolve an environment-provided path relative to the project root."""
    raw_value = value.strip()
    if not raw_value:
        return str(default_path) if default_path else ""

    path_value = Path(raw_value).expanduser()
    if not path_value.is_absolute():
        path_value = (BASE_DIR / path_value).resolve()
    return str(path_value)


@dataclass(frozen=True)
class Settings:
    """Store application configuration and resolved filesystem paths."""

    nvidia_api_key: str
    deepseek_model: str
    wan_model: str
    wan_replicate_model: str
    wan_resolution: str
    wan_num_frames: int
    replicate_api_token: str
    magpie_tts_model: str
    frontend_host: str
    frontend_port: int
    log_level: str
    base_dir: Path
    assets_dir: Path
    images_dir: Path
    videos_dir: Path
    audio_dir: Path
    output_dir: Path
    prompts_dir: Path
    jobs_dir: Path
    web_dir: Path
    youtube_client_secrets_file: str
    youtube_token_file: str
    youtube_category_id: str


def _build_settings() -> Settings:
    """Create the settings object and ensure required directories exist."""
    assets_dir = BASE_DIR / "assets"
    images_dir = assets_dir / "images"
    audio_dir = assets_dir / "audio"
    output_dir = BASE_DIR / "output"
    prompts_dir = BASE_DIR / "prompts"
    videos_dir = BASE_DIR / "videos"
    jobs_dir = output_dir / "jobs"
    web_dir = BASE_DIR / "web"

    for directory in (
        assets_dir,
        images_dir,
        audio_dir,
        output_dir,
        prompts_dir,
        videos_dir,
        jobs_dir,
        web_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    return Settings(
        nvidia_api_key=os.getenv("NVIDIA_API_KEY", "").strip(),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-ai/deepseek-v3.2").strip(),
        wan_model=os.getenv("WAN_MODEL", "Wan 2.2 T2V").strip(),
        wan_replicate_model=os.getenv("WAN_REPLICATE_MODEL", "wavespeed-ai/wan-2.2-t2v-480p").strip(),
        wan_resolution=os.getenv("WAN_RESOLUTION", "720p").strip() or "720p",
        wan_num_frames=int(os.getenv("WAN_NUM_FRAMES", "81")),
        replicate_api_token=os.getenv("REPLICATE_API_TOKEN", "").strip(),
        magpie_tts_model=os.getenv(
            "MAGPIE_TTS_MODEL",
            "MagpieTTS Multilingual",
        ).strip(),
        frontend_host=os.getenv("FRONTEND_HOST", "127.0.0.1").strip() or "127.0.0.1",
        frontend_port=int(os.getenv("FRONTEND_PORT", "8000")),
        log_level=log_level,
        base_dir=BASE_DIR,
        assets_dir=assets_dir,
        images_dir=images_dir,
        videos_dir=videos_dir,
        audio_dir=audio_dir,
        output_dir=output_dir,
        prompts_dir=prompts_dir,
        jobs_dir=jobs_dir,
        web_dir=web_dir,
        youtube_client_secrets_file=_resolve_env_path(
            os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "")
        ),
        youtube_token_file=_resolve_env_path(
            os.getenv("YOUTUBE_TOKEN_FILE", ""),
            default_path=output_dir / "youtube_token.json",
        ),
        youtube_category_id=os.getenv("YOUTUBE_CATEGORY_ID", "28").strip() or "28",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings object for the current process."""
    return _build_settings()
