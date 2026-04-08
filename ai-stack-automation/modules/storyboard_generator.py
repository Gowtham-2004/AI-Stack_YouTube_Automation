"""Generate a structured 12-scene storyboard using NVIDIA-hosted DeepSeek."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import requests

from config.settings import Settings


LOGGER = logging.getLogger(__name__)
NVIDIA_CHAT_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
SCENE_COUNT = 12
SCENE_DURATION_SECONDS = 5


@dataclass(frozen=True)
class StoryboardScene:
    """A single tightly aligned audio-video scene."""

    scene_number: int
    narration: str
    video_prompt: str
    subtitle: str
    visual_focus: str
    duration_seconds: int = SCENE_DURATION_SECONDS


@dataclass(frozen=True)
class Storyboard:
    """Top-level video plan returned by the model."""

    title: str
    summary: str
    scenes: list[StoryboardScene]


def _build_prompt(topic: str) -> str:
    return f"""
Create a storyboard for a 60-second educational YouTube short about "{topic.strip()}".

Return valid JSON only. Do not wrap the JSON in markdown fences.

Required JSON shape:
{{
  "title": "short title",
  "summary": "one sentence overview",
  "scenes": [
    {{
      "scene_number": 1,
      "narration": "one short English sentence that fits in about 5 seconds",
      "video_prompt": "a vivid text-to-video prompt for the same idea",
      "subtitle": "short subtitle line",
      "visual_focus": "2-5 word label"
    }}
  ]
}}

Rules:
- Return exactly 12 scenes.
- Each scene must represent about 5 seconds.
- Narration and video prompt must describe the same moment.
- Narration must be concise, clear, and in English.
- Visuals should feel modern, clean, and educational.
- Scene 1 must be a hook.
- Scene 12 must feel like a short wrap-up.
""".strip()


def _extract_json_blob(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("The model response did not contain a JSON object.")
    return cleaned[start : end + 1]


def _fallback_storyboard(topic: str) -> Storyboard:
    scenes: list[StoryboardScene] = []
    scene_templates = [
        ("Hook", f"{topic} is changing how modern AI answers real questions."),
        ("Problem", "Large language models can sound fluent while missing the right facts."),
        ("Retrieval", "Retrieval adds trusted sources before the model writes a response."),
        ("Chunking", "Documents are split into searchable chunks for fast lookup."),
        ("Embedding", "Each chunk becomes a vector so similar ideas sit near each other."),
        ("Search", "A user query pulls the most relevant chunks from the database."),
        ("Context", "Those retrieved snippets are packed into the model context window."),
        ("Answer", "The model now answers with source-backed context instead of guessing."),
        ("Benefit", "That makes answers more relevant, traceable, and easier to trust."),
        ("Use Case", "Teams use this flow for support bots, docs search, and internal knowledge."),
        ("Takeaway", f"The core idea of {topic} is retrieval first, generation second."),
        ("Wrap-Up", "That simple pattern turns static data into useful AI conversations."),
    ]
    for index, (focus, narration) in enumerate(scene_templates, start=1):
        scenes.append(
            StoryboardScene(
                scene_number=index,
                narration=narration,
                subtitle=narration,
                visual_focus=focus,
                video_prompt=(
                    f"Create a polished cinematic educational motion graphic for scene {index} "
                    f"about {topic}. Focus on {focus.lower()}, clean UI-inspired visuals, "
                    "modern lighting, subtle camera motion, bold typography, and clear visual storytelling."
                ),
            )
        )
    return Storyboard(
        title=f"{topic.strip().title()} in 60 Seconds",
        summary=f"A 12-scene explainer about {topic.strip()}",
        scenes=scenes,
    )


def _parse_storyboard(payload: dict) -> Storyboard:
    scenes_raw = payload.get("scenes") or []
    if len(scenes_raw) != SCENE_COUNT:
        raise ValueError(f"Expected {SCENE_COUNT} scenes but received {len(scenes_raw)}.")

    scenes: list[StoryboardScene] = []
    for index, raw_scene in enumerate(scenes_raw, start=1):
        scenes.append(
            StoryboardScene(
                scene_number=int(raw_scene.get("scene_number", index)),
                narration=str(raw_scene.get("narration", "")).strip(),
                video_prompt=str(raw_scene.get("video_prompt", "")).strip(),
                subtitle=str(raw_scene.get("subtitle", "")).strip()
                or str(raw_scene.get("narration", "")).strip(),
                visual_focus=str(raw_scene.get("visual_focus", f"Scene {index}")).strip(),
                duration_seconds=SCENE_DURATION_SECONDS,
            )
        )

    if not all(scene.narration and scene.video_prompt for scene in scenes):
        raise ValueError("One or more scenes were missing narration or a video prompt.")

    return Storyboard(
        title=str(payload.get("title", "AI Stack Automation")).strip() or "AI Stack Automation",
        summary=str(payload.get("summary", "")).strip(),
        scenes=scenes,
    )


def generate_storyboard(topic: str, settings: Settings) -> Storyboard:
    """Generate a 12-scene storyboard, with a deterministic fallback for offline use."""
    if not topic.strip():
        raise ValueError("Topic is empty.")

    if not settings.nvidia_api_key:
        LOGGER.warning("NVIDIA_API_KEY is missing. Using fallback storyboard generation.")
        return _fallback_storyboard(topic)

    headers = {
        "Authorization": f"Bearer {settings.nvidia_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {
                "role": "system",
                "content": "You are a precise storyboard planner for short educational videos.",
            },
            {
                "role": "user",
                "content": _build_prompt(topic),
            },
        ],
        "temperature": 0.5,
        "top_p": 0.9,
        "max_tokens": 2800,
    }

    try:
        response = requests.post(
            NVIDIA_CHAT_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=180,
        )
        response.raise_for_status()
        data = response.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed = json.loads(_extract_json_blob(content))
        return _parse_storyboard(parsed)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("Falling back to local storyboard generation: %s", exc)
        return _fallback_storyboard(topic)
