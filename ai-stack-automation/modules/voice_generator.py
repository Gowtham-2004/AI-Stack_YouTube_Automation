"""Convert scripts into speech using the ElevenLabs API."""

from __future__ import annotations

import logging

import requests

from config.settings import Settings


LOGGER = logging.getLogger(__name__)
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1/text-to-speech"


def generate_voice(script_text: str, settings: Settings) -> str:
    """Generate MP3 narration from script text and save it to disk."""
    if not script_text.strip():
        raise ValueError("Script text is empty.")

    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY is not set in the environment.")

    endpoint = f"{ELEVENLABS_BASE_URL}/{settings.elevenlabs_voice_id}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": settings.elevenlabs_api_key,
    }
    payload = {
        "text": script_text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.8,
        },
    }

    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=180)
        response.raise_for_status()
    except requests.RequestException as exc:
        LOGGER.exception("ElevenLabs request failed.")
        raise RuntimeError(f"Failed to generate voice audio: {exc}") from exc

    settings.voice_output_path.write_bytes(response.content)
    LOGGER.info("Voice-over saved to %s", settings.voice_output_path)
    return str(settings.voice_output_path)
