"""Build a scene-based video from aligned audio and richer topic-aware visual clips."""

from __future__ import annotations

import logging
import math
import random
import textwrap
import time
import wave
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:
    from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip, VideoFileClip, concatenate_videoclips
except ImportError:  # pragma: no cover
    from moviepy.editor import AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip, VideoFileClip, concatenate_videoclips

from config.settings import Settings
from modules.storyboard_generator import Storyboard


LOGGER = logging.getLogger(__name__)
VIDEO_SIZE = (1280, 720)
FPS = 24
MUSIC_SAMPLE_RATE = 22_050
WAN_REPLICATE_BASE_URL = "https://api.replicate.com/v1"
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"}


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in ("Arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _scene_palette(scene_number: int) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    palettes = [
        ((7, 28, 56), (15, 122, 162), (255, 206, 102)),
        ((36, 18, 70), (206, 86, 118), (131, 229, 207)),
        ((8, 48, 45), (76, 184, 150), (255, 225, 127)),
        ((58, 30, 16), (233, 144, 82), (115, 221, 255)),
    ]
    return palettes[(scene_number - 1) % len(palettes)]


def _draw_gradient(draw: ImageDraw.ImageDraw, base: tuple[int, int, int], accent: tuple[int, int, int]) -> None:
    width, height = VIDEO_SIZE
    for row in range(height):
        ratio = row / max(height - 1, 1)
        red = int(base[0] * (1 - ratio) + accent[0] * ratio)
        green = int(base[1] * (1 - ratio) + accent[1] * ratio)
        blue = int(base[2] * (1 - ratio) + accent[2] * ratio)
        draw.line((0, row, width, row), fill=(red, green, blue))


def _draw_orb_layer(image: Image.Image, accent: tuple[int, int, int], seed: int) -> None:
    rng = random.Random(seed)
    orb_layer = Image.new("RGBA", VIDEO_SIZE, (0, 0, 0, 0))
    orb_draw = ImageDraw.Draw(orb_layer)
    for _ in range(7):
        radius = rng.randint(80, 180)
        center_x = rng.randint(80, VIDEO_SIZE[0] - 80)
        center_y = rng.randint(60, VIDEO_SIZE[1] - 60)
        fill = (*accent, rng.randint(28, 54))
        orb_draw.ellipse(
            (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
            fill=fill,
        )
    blurred = orb_layer.filter(ImageFilter.GaussianBlur(radius=36))
    image.alpha_composite(blurred)


def _draw_grid(draw: ImageDraw.ImageDraw) -> None:
    for x in range(0, VIDEO_SIZE[0], 48):
        draw.line((x, 0, x, VIDEO_SIZE[1]), fill=(255, 255, 255, 18), width=1)
    for y in range(0, VIDEO_SIZE[1], 48):
        draw.line((0, y, VIDEO_SIZE[0], y), fill=(255, 255, 255, 18), width=1)


def _rounded_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: tuple[int, int, int, int], outline: tuple[int, int, int, int] | None = None) -> None:
    draw.rounded_rectangle(box, radius=28, fill=fill, outline=outline, width=2 if outline else 1)


def _draw_chip_label(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font: ImageFont.ImageFont, fill: tuple[int, int, int, int]) -> None:
    box = (x, y, x + 110, y + 38)
    draw.rounded_rectangle(box, radius=18, fill=fill)
    draw.text((x + 16, y + 10), text, font=font, fill=(28, 32, 44))


def _draw_database(draw: ImageDraw.ImageDraw, center_x: int, center_y: int, scale: float) -> None:
    width = int(154 * scale)
    height = int(54 * scale)
    body_height = int(178 * scale)
    left = center_x - width // 2
    right = center_x + width // 2
    top = center_y - body_height // 2
    bottom = top + body_height
    fill = (241, 247, 255, 255)
    stroke = (49, 88, 152, 255)
    draw.ellipse((left, top, right, top + height), fill=fill, outline=stroke, width=4)
    draw.rectangle((left, top + height // 2, right, bottom - height // 2), fill=fill, outline=stroke, width=4)
    draw.ellipse((left, bottom - height, right, bottom), fill=fill, outline=stroke, width=4)
    for band in range(1, 4):
        y = top + band * 42 * scale
        draw.arc((left, y - height // 2, right, y + height // 2), 0, 180, fill=stroke, width=3)


def _draw_document(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float, fill: tuple[int, int, int, int]) -> None:
    width = int(112 * scale)
    height = int(144 * scale)
    fold = int(28 * scale)
    draw.rounded_rectangle((x, y, x + width, y + height), radius=18, fill=fill, outline=(40, 56, 84, 255), width=3)
    draw.polygon([(x + width - fold, y), (x + width, y), (x + width, y + fold)], fill=(224, 232, 252, 255))
    for row in range(4):
        top = y + 32 + row * 22
        draw.line((x + 16, top, x + width - 18, top), fill=(99, 118, 149, 255), width=4)


def _draw_magnifier(draw: ImageDraw.ImageDraw, center_x: int, center_y: int, scale: float) -> None:
    radius = int(54 * scale)
    draw.ellipse((center_x - radius, center_y - radius, center_x + radius, center_y + radius), outline=(255, 250, 240, 255), width=10)
    handle_len = int(82 * scale)
    draw.line(
        (center_x + radius // 2, center_y + radius // 2, center_x + radius // 2 + handle_len, center_y + radius // 2 + handle_len),
        fill=(255, 250, 240, 255),
        width=10,
    )


def _draw_chip(draw: ImageDraw.ImageDraw, center_x: int, center_y: int, scale: float) -> None:
    size = int(144 * scale)
    left = center_x - size // 2
    top = center_y - size // 2
    draw.rounded_rectangle((left, top, left + size, top + size), radius=20, fill=(255, 250, 237, 255), outline=(56, 65, 89, 255), width=4)
    inner = 40
    draw.rounded_rectangle((left + inner, top + inner, left + size - inner, top + size - inner), radius=16, outline=(83, 116, 214, 255), width=4)
    for index in range(8):
        offset = 14 + index * 15
        draw.line((left - 18, top + offset, left, top + offset), fill=(255, 250, 237, 255), width=4)
        draw.line((left + size, top + offset, left + size + 18, top + offset), fill=(255, 250, 237, 255), width=4)
        draw.line((left + offset, top - 18, left + offset, top), fill=(255, 250, 237, 255), width=4)
        draw.line((left + offset, top + size, left + offset, top + size + 18), fill=(255, 250, 237, 255), width=4)


def _draw_chart(draw: ImageDraw.ImageDraw, x: int, y: int, accent: tuple[int, int, int]) -> None:
    draw.rounded_rectangle((x, y, x + 270, y + 150), radius=24, fill=(255, 255, 255, 44))
    points = [(x + 24, y + 120), (x + 84, y + 96), (x + 138, y + 102), (x + 194, y + 66), (x + 244, y + 48)]
    draw.line(points, fill=(*accent, 255), width=6)
    for point in points:
        draw.ellipse((point[0] - 7, point[1] - 7, point[0] + 7, point[1] + 7), fill=(255, 250, 240, 255))


def _draw_node_graph(draw: ImageDraw.ImageDraw, x: int, y: int, accent: tuple[int, int, int]) -> None:
    nodes = [(x + 40, y + 42), (x + 148, y + 34), (x + 92, y + 104), (x + 204, y + 104), (x + 252, y + 48)]
    for start, end in ((0, 1), (0, 2), (1, 3), (1, 4), (2, 3), (3, 4)):
        draw.line((nodes[start][0], nodes[start][1], nodes[end][0], nodes[end][1]), fill=(255, 255, 255, 110), width=3)
    for node in nodes:
        draw.ellipse((node[0] - 14, node[1] - 14, node[0] + 14, node[1] + 14), fill=(*accent, 255), outline=(255, 250, 240, 255), width=3)


def _draw_code_panel(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.rounded_rectangle((x, y, x + 310, y + 180), radius=24, fill=(14, 19, 31, 220), outline=(111, 211, 245, 120), width=2)
    for index, width in enumerate((220, 198, 240, 176, 210)):
        top = y + 34 + index * 26
        draw.line((x + 24, top, x + 24 + width, top), fill=(124, 236, 192, 255), width=4)


def _draw_flow_arrows(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: tuple[int, int, int, int]) -> None:
    draw.line((start[0], start[1], end[0], end[1]), fill=color, width=8)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    arrow_size = 18
    left = (end[0] - arrow_size * math.cos(angle - math.pi / 6), end[1] - arrow_size * math.sin(angle - math.pi / 6))
    right = (end[0] - arrow_size * math.cos(angle + math.pi / 6), end[1] - arrow_size * math.sin(angle + math.pi / 6))
    draw.polygon([end, left, right], fill=color)


def _draw_keyword_visuals(draw: ImageDraw.ImageDraw, text_blob: str, accent: tuple[int, int, int]) -> None:
    lowered = text_blob.lower()
    if any(keyword in lowered for keyword in ("database", "store", "retriev", "vector", "index")):
        _draw_database(draw, 955, 250, 1.0)
        _draw_chart(draw, 840, 384, accent)
    if any(keyword in lowered for keyword in ("document", "chunk", "source", "context", "knowledge")):
        _draw_document(draw, 806, 176, 1.0, (248, 244, 255, 255))
        _draw_document(draw, 918, 210, 0.92, (236, 248, 255, 255))
        _draw_document(draw, 1032, 248, 0.84, (244, 255, 244, 255))
    if any(keyword in lowered for keyword in ("search", "query", "find", "retrieve")):
        _draw_magnifier(draw, 1088, 170, 0.95)
    if any(keyword in lowered for keyword in ("model", "ai", "generation", "answer", "llm")):
        _draw_chip(draw, 1092, 326, 0.86)
        _draw_node_graph(draw, 834, 486, accent)
    if any(keyword in lowered for keyword in ("workflow", "pipeline", "step", "process", "flow")):
        _draw_flow_arrows(draw, (812, 608), (926, 608), (*accent, 255))
        _draw_flow_arrows(draw, (948, 608), (1062, 608), (*accent, 255))
        _draw_flow_arrows(draw, (1084, 608), (1196, 608), (*accent, 255))
    _draw_code_panel(draw, 820, 474)


def _render_scene_image(
    output_path: Path,
    topic: str,
    scene_number: int,
    visual_focus: str,
    subtitle: str,
    video_prompt: str,
) -> Path:
    """Create a richer topic-aware explainer frame."""
    base, accent, contrast = _scene_palette(scene_number)
    image = Image.new("RGBA", VIDEO_SIZE, (*base, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    _draw_gradient(draw, base=base, accent=accent)
    _draw_orb_layer(image, accent=accent, seed=scene_number)
    _draw_grid(draw)

    title_font = _load_font(28)
    focus_font = _load_font(66)
    body_font = _load_font(26)
    small_font = _load_font(20)

    _rounded_panel(draw, (44, 40, 1236, 680), (255, 255, 255, 16), (255, 255, 255, 60))
    _rounded_panel(draw, (70, 70, 474, 118), (255, 255, 255, 34))
    draw.text((92, 84), f"{topic.title()}  |  Scene {scene_number:02d}", font=title_font, fill=(248, 251, 255, 255))

    _rounded_panel(draw, (78, 150, 720, 556), (247, 249, 253, 255))
    _rounded_panel(draw, (98, 170, 692, 232), (18, 28, 44, 235))
    draw.text((122, 186), visual_focus, font=focus_font, fill=(255, 255, 255, 255))

    wrapped_subtitle = textwrap.fill(subtitle.strip(), width=34)
    draw.text((122, 278), wrapped_subtitle, font=body_font, fill=(56, 68, 90, 255))

    draw.rounded_rectangle((122, 438, 318, 478), radius=18, fill=(*contrast, 255))
    draw.text((142, 448), "Scene Focus", font=small_font, fill=(30, 34, 46, 255))
    draw.rounded_rectangle((340, 438, 554, 478), radius=18, fill=(227, 241, 255, 255))
    draw.text((360, 448), textwrap.shorten(visual_focus, width=18, placeholder="..."), font=small_font, fill=(36, 52, 74, 255))

    _rounded_panel(draw, (98, 506, 700, 610), (242, 246, 255, 255))
    teaser = textwrap.shorten(video_prompt.strip(), width=80, placeholder="...")
    draw.text((122, 534), teaser, font=small_font, fill=(74, 89, 112, 255))

    _rounded_panel(draw, (758, 126, 1188, 628), (255, 255, 255, 34))
    _draw_keyword_visuals(draw, f"{topic} {visual_focus} {subtitle} {video_prompt}", accent=contrast)

    _draw_chip_label(draw, 790, 148, "Input", small_font, (255, 244, 212, 255))
    _draw_chip_label(draw, 914, 148, "Retrieve", small_font, (222, 248, 243, 255))
    _draw_chip_label(draw, 1038, 148, "Generate", small_font, (231, 236, 255, 255))

    draw.rounded_rectangle((88, 630, 1192, 670), radius=20, fill=(16, 22, 34, 228))
    caption = textwrap.shorten(subtitle.strip(), width=110, placeholder="...")
    draw.text((118, 641), caption, font=small_font, fill=(255, 255, 255, 255))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output_path)
    return output_path


def _build_cinematic_prompt(topic: str, visual_focus: str, subtitle: str, video_prompt: str) -> str:
    return (
        f"{topic}. {visual_focus}. {subtitle}. {video_prompt}. "
        "Cinematic composition, dynamic camera motion, volumetric lighting, "
        "high-detail textures, depth of field, color graded for modern documentary style, "
        "smooth transitions, visually rich and engaging."
    )


def _create_replicate_prediction(
    scene_number: int,
    prompt: str,
    settings: Settings,
) -> dict:
    owner, model = settings.wan_replicate_model.split("/", maxsplit=1)
    endpoint = f"{WAN_REPLICATE_BASE_URL}/models/{owner}/{model}/predictions"
    headers = {
        "Authorization": f"Token {settings.replicate_api_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": {
            "prompt": prompt,
            "num_frames": settings.wan_num_frames,
            "resolution": settings.wan_resolution,
        }
    }
    response = requests.post(endpoint, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    prediction = response.json()
    LOGGER.info("Scene %s Wan prediction created: %s", scene_number, prediction.get("id"))
    return prediction


def _wait_for_replicate_prediction(scene_number: int, prediction_id: str, settings: Settings) -> dict:
    headers = {"Authorization": f"Token {settings.replicate_api_token}"}
    status_endpoint = f"{WAN_REPLICATE_BASE_URL}/predictions/{prediction_id}"
    deadline = time.time() + 15 * 60

    while time.time() < deadline:
        response = requests.get(status_endpoint, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()
        status = str(data.get("status", "")).lower()
        if status == "succeeded":
            LOGGER.info("Scene %s Wan prediction succeeded.", scene_number)
            return data
        if status in {"failed", "canceled"}:
            error_message = data.get("error") or f"Prediction status: {status}"
            raise RuntimeError(f"Wan prediction failed for scene {scene_number}: {error_message}")
        time.sleep(4)

    raise TimeoutError(f"Wan prediction timed out for scene {scene_number}.")


def _download_replicate_output(output_data: object, output_path: Path) -> Path:
    if isinstance(output_data, list) and output_data:
        url = str(output_data[0])
    else:
        url = str(output_data)
    if not url.startswith("http"):
        raise ValueError("Wan output did not include a downloadable URL.")

    response = requests.get(url, timeout=180)
    response.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)
    return output_path


def _generate_wan_scene_clip(
    topic: str,
    scene_number: int,
    visual_focus: str,
    subtitle: str,
    video_prompt: str,
    output_path: Path,
    settings: Settings,
) -> Path | None:
    if not settings.replicate_api_token:
        return None
    try:
        cinematic_prompt = _build_cinematic_prompt(
            topic=topic,
            visual_focus=visual_focus,
            subtitle=subtitle,
            video_prompt=video_prompt,
        )
        prediction = _create_replicate_prediction(
            scene_number=scene_number,
            prompt=cinematic_prompt,
            settings=settings,
        )
        completed = _wait_for_replicate_prediction(
            scene_number=scene_number,
            prediction_id=str(prediction["id"]),
            settings=settings,
        )
        return _download_replicate_output(completed.get("output"), output_path=output_path)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("Scene %s Wan generation failed, using fallback visuals: %s", scene_number, exc)
        return None


def build_scene_assets(
    storyboard: Storyboard,
    topic: str,
    scene_assets_dir: Path,
    audio_paths: list[Path],
    settings: Settings,
) -> list[Path]:
    """Generate one richer topic-aware visual asset per scene.

    Uses Wan 2.2 via Replicate when configured, otherwise falls back to local graphics.
    """
    generated_images: list[Path] = []
    for scene, audio_path in zip(storyboard.scenes, audio_paths, strict=True):
        scene_clip_path = scene_assets_dir / f"scene_{scene.scene_number:02d}.mp4"
        wan_output = _generate_wan_scene_clip(
            topic=topic,
            scene_number=scene.scene_number,
            visual_focus=scene.visual_focus,
            subtitle=scene.subtitle,
            video_prompt=scene.video_prompt,
            output_path=scene_clip_path,
            settings=settings,
        )

        if wan_output is not None and wan_output.exists():
            generated_images.append(wan_output)
            LOGGER.info(
                "Scene %s cinematic video generated with %s and aligned to %s.",
                scene.scene_number,
                settings.wan_replicate_model,
                audio_path.name,
            )
            continue

        image_path = scene_assets_dir / f"scene_{scene.scene_number:02d}.png"
        _render_scene_image(
            output_path=image_path,
            topic=topic,
            scene_number=scene.scene_number,
            visual_focus=scene.visual_focus,
            subtitle=scene.subtitle,
            video_prompt=scene.video_prompt,
        )
        generated_images.append(image_path)
        LOGGER.info(
            "Scene %s fallback visual prepared for model %s with aligned audio %s.",
            scene.scene_number,
            settings.wan_model,
            audio_path.name,
        )
    return generated_images


def _write_background_music(output_path: Path, duration: float, seed: int) -> Path:
    """Create a soft ambient backing track for the current scene."""
    sample_rate = MUSIC_SAMPLE_RATE
    frame_count = max(int(sample_rate * duration), 1)
    rng = random.Random(seed * 97)
    root_frequency = rng.choice((174.61, 196.0, 220.0, 246.94))
    harmony_frequency = root_frequency * rng.choice((1.25, 1.333, 1.5))
    pulse_frequency = root_frequency / 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        frames = bytearray()
        for frame in range(frame_count):
            time_value = frame / sample_rate
            fade_in = min(1.0, time_value / 0.8)
            fade_out = min(1.0, max(duration - time_value, 0) / 1.0)
            envelope = fade_in * fade_out
            pad = math.sin(2 * math.pi * root_frequency * time_value)
            harmony = math.sin(2 * math.pi * harmony_frequency * time_value)
            pulse = math.sin(2 * math.pi * pulse_frequency * time_value) * math.sin(2 * math.pi * 0.6 * time_value)
            sample = int(2200 * envelope * (0.6 * pad + 0.28 * harmony + 0.12 * pulse))
            frames.extend(int(sample).to_bytes(2, byteorder="little", signed=True))
        wav_file.writeframes(frames)
    return output_path


def _make_motion_clip(image_path: Path, duration: float, audio_clip: AudioFileClip, scene_number: int):
    base_clip = ImageClip(str(image_path)).with_duration(duration)
    start_zoom = 1.0 + (scene_number % 3) * 0.015
    end_zoom = start_zoom + 0.045

    def zoom_factor(time_value: float) -> float:
        if duration <= 0:
            return end_zoom
        return start_zoom + (end_zoom - start_zoom) * (time_value / duration)

    moving_clip = base_clip.resized(lambda t: zoom_factor(t)).with_position("center")
    composite = CompositeVideoClip([moving_clip], size=VIDEO_SIZE).with_duration(duration).with_audio(audio_clip)
    return composite, base_clip, moving_clip


def _make_video_clip(video_path: Path, duration: float, audio_clip: AudioFileClip):
    video_clip = VideoFileClip(str(video_path)).without_audio()
    if (video_clip.duration or 0) >= duration:
        visual_clip = video_clip.subclipped(0, duration)
    else:
        visual_clip = video_clip.with_duration(duration)
    visual_clip = visual_clip.resized(VIDEO_SIZE)
    composite = visual_clip.with_audio(audio_clip).with_duration(duration)
    return composite, video_clip, visual_clip


def create_aligned_video(
    storyboard: Storyboard,
    image_paths: list[Path],
    audio_paths: list[Path],
    output_path: Path,
) -> Path:
    """Create a final MP4 where each scene has matched voiceover and gentle motion."""
    scene_clips = []
    audio_clips: list[AudioFileClip] = []
    music_clips: list[AudioFileClip] = []
    base_clips = []
    moving_clips = []
    source_video_clips = []
    final_video_clips = []
    final_clip = None
    music_dir = output_path.parent.parent / "output" / "music_beds"
    music_paths: list[Path] = []

    try:
        for scene, image_path, audio_path in zip(storyboard.scenes, image_paths, audio_paths, strict=True):
            voice_clip = AudioFileClip(str(audio_path))
            audio_clips.append(voice_clip)

            duration = voice_clip.duration or scene.duration_seconds
            music_path = _write_background_music(
                output_path=music_dir / f"scene_{scene.scene_number:02d}_bed.wav",
                duration=duration,
                seed=scene.scene_number,
            )
            music_paths.append(music_path)
            music_clip = AudioFileClip(str(music_path)).with_volume_scaled(0.12)
            music_clips.append(music_clip)
            mixed_audio = CompositeAudioClip(
                [
                    music_clip,
                    voice_clip.with_volume_scaled(1.35),
                ]
            ).with_duration(duration)
            if image_path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
                composite, source_video, final_video = _make_video_clip(
                    video_path=image_path,
                    duration=duration,
                    audio_clip=mixed_audio,
                )
                scene_clips.append(composite)
                source_video_clips.append(source_video)
                final_video_clips.append(final_video)
            else:
                composite, base_clip, moving_clip = _make_motion_clip(
                    image_path=image_path,
                    duration=duration,
                    audio_clip=mixed_audio,
                    scene_number=scene.scene_number,
                )
                scene_clips.append(composite)
                base_clips.append(base_clip)
                moving_clips.append(moving_clip)

        final_clip = concatenate_videoclips(scene_clips, method="compose")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        final_clip.write_videofile(
            str(output_path),
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
        )
    finally:
        if final_clip is not None:
            final_clip.close()
        for clip in scene_clips:
            clip.close()
        for clip in moving_clips:
            clip.close()
        for clip in base_clips:
            clip.close()
        for clip in final_video_clips:
            clip.close()
        for clip in source_video_clips:
            clip.close()
        for audio_clip in audio_clips:
            audio_clip.close()
        for music_clip in music_clips:
            music_clip.close()

    LOGGER.info("Aligned final video saved to %s", output_path)
    return output_path
