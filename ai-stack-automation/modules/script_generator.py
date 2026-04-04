"""Generate YouTube scripts using the OpenAI API."""

from __future__ import annotations

import logging
from pathlib import Path

from openai import OpenAI

from config.settings import Settings


LOGGER = logging.getLogger(__name__)


def _load_prompt_template(prompt_path: Path) -> str:
    """Load the reusable script prompt template from disk."""
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def generate_script(topic: str, settings: Settings) -> str:
    """Generate a structured 6-8 minute YouTube script for the given topic."""
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set in the environment.")

    prompt_template = _load_prompt_template(settings.script_prompt_path)
    client = OpenAI(api_key=settings.openai_api_key)
    final_prompt = prompt_template.format(topic=topic.strip())

    try:
        response = client.responses.create(
            model=settings.openai_model,
            input=final_prompt,
        )
        script_text = (response.output_text or "").strip()
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("OpenAI request failed.")
        raise RuntimeError(f"Failed to generate script: {exc}") from exc

    if not script_text:
        raise RuntimeError("OpenAI returned an empty script.")

    settings.script_output_path.write_text(script_text, encoding="utf-8")
    LOGGER.info("Script saved to %s", settings.script_output_path)
    return script_text
