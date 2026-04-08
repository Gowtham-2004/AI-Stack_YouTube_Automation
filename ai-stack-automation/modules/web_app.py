"""Local web app and background job pipeline for video generation."""

from __future__ import annotations

import json
import logging
import threading
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from config.settings import Settings
from modules.storyboard_generator import Storyboard, generate_storyboard
from modules.video_creator import build_scene_assets, create_aligned_video
from modules.voice_generator import generate_scene_audio


LOGGER = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in value)
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed[:60] or "video-topic"


@dataclass
class SceneStatus:
    scene_number: int
    visual_focus: str
    narration: str = ""
    status: str = "pending"
    message: str = "Waiting"


@dataclass
class JobState:
    job_id: str
    topic: str
    status: str = "queued"
    stage: str = "Queued"
    message: str = "Waiting to start"
    progress: int = 0
    title: str = ""
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    video_path: str = ""
    video_url: str = ""
    scenes: list[SceneStatus] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "topic": self.topic,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "progress": self.progress,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "video_path": self.video_path,
            "video_url": self.video_url,
            "error": self.error,
            "scenes": [asdict(scene) for scene in self.scenes],
        }


class JobStore:
    """Thread-safe in-memory job state store."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()

    def create(self, topic: str) -> JobState:
        with self._lock:
            job = JobState(job_id=uuid.uuid4().hex[:10], topic=topic.strip())
            self._jobs[job.job_id] = job
            return job

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: Any) -> JobState:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = _utc_now()
            return job

    def set_scenes(self, job_id: str, scenes: list[SceneStatus]) -> None:
        self.update(job_id, scenes=scenes)

    def update_scene(self, job_id: str, scene_number: int, **changes: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for scene in job.scenes:
                if scene.scene_number == scene_number:
                    for key, value in changes.items():
                        setattr(scene, key, value)
                    break
            job.updated_at = _utc_now()


def _progress_for_scene(step_index: int, scene_number: int) -> int:
    base = 15 + (scene_number - 1) * 6
    return min(90, base + step_index * 3)


def _write_storyboard_debug(storyboard: Storyboard, path: Path) -> None:
    payload = {
        "title": storyboard.title,
        "summary": storyboard.summary,
        "scenes": [asdict(scene) for scene in storyboard.scenes],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_generation_job(job_store: JobStore, job_id: str, settings: Settings) -> None:
    """Execute the 12-scene pipeline in a background thread."""
    job = job_store.get(job_id)
    if job is None:
        return

    topic = job.topic
    job_dir = settings.jobs_dir / job_id
    audio_dir = job_dir / "audio"
    image_dir = job_dir / "images"
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        job_store.update(
            job_id,
            status="running",
            stage="Generating storyboard",
            message="Creating a 12-scene plan with DeepSeek",
            progress=5,
        )
        storyboard = generate_storyboard(topic=topic, settings=settings)
        job_store.update(job_id, title=storyboard.title)
        job_store.set_scenes(
            job_id,
            [
                SceneStatus(
                    scene_number=scene.scene_number,
                    visual_focus=scene.visual_focus,
                    narration=scene.narration,
                )
                for scene in storyboard.scenes
            ],
        )
        _write_storyboard_debug(storyboard, job_dir / "storyboard.json")

        audio_paths: list[Path] = []
        for scene in storyboard.scenes:
            job_store.update_scene(
                job_id,
                scene.scene_number,
                status="audio",
                message="Generating audio",
            )
            job_store.update(
                job_id,
                stage=f"Generating audio for scene {scene.scene_number}",
                message=f"Preparing scene {scene.scene_number} narration",
                progress=_progress_for_scene(0, scene.scene_number),
            )
            audio_path = generate_scene_audio(
                scene_number=scene.scene_number,
                narration_text=scene.narration,
                output_path=audio_dir / f"scene_{scene.scene_number:02d}.wav",
                settings=settings,
            )
            audio_paths.append(audio_path)
            job_store.update_scene(
                job_id,
                scene.scene_number,
                status="audio_done",
                message="Audio ready",
            )

        job_store.update(
            job_id,
            stage="Generating visuals",
            message=f"Preparing visuals with {settings.wan_model}",
            progress=55,
        )
        image_paths = build_scene_assets(
            storyboard=storyboard,
            topic=topic,
            scene_assets_dir=image_dir,
            audio_paths=audio_paths,
            settings=settings,
        )

        for scene in storyboard.scenes:
            job_store.update_scene(
                job_id,
                scene.scene_number,
                status="visual_done",
                message="Visual ready",
            )

        job_store.update(
            job_id,
            stage="Aligning scenes",
            message="Syncing scene visuals to the matching audio durations",
            progress=80,
        )
        video_name = f"{_slugify(topic)}-{job_id}.mp4"
        final_video_path = settings.videos_dir / video_name
        create_aligned_video(
            storyboard=storyboard,
            image_paths=image_paths,
            audio_paths=audio_paths,
            output_path=final_video_path,
        )

        for scene in storyboard.scenes:
            job_store.update_scene(
                job_id,
                scene.scene_number,
                status="done",
                message="Aligned",
            )

        job_store.update(
            job_id,
            status="completed",
            stage="Completed",
            message="Video generated successfully",
            progress=100,
            video_path=str(final_video_path),
            video_url=f"/videos/{final_video_path.name}",
        )
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Job %s failed.", job_id)
        job_store.update(
            job_id,
            status="failed",
            stage="Failed",
            message="Video generation failed",
            error=str(exc),
        )


def build_handler(job_store: JobStore, settings: Settings):
    """Build an HTTP handler bound to the shared store."""

    class AppHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(settings.web_dir), **kwargs)

        def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/jobs":
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
            data = json.loads(raw_body or "{}")
            topic = str(data.get("topic", "")).strip()

            if not topic:
                self._send_json({"error": "Topic is required."}, status=HTTPStatus.BAD_REQUEST)
                return

            job = job_store.create(topic)
            worker = threading.Thread(
                target=run_generation_job,
                args=(job_store, job.job_id, settings),
                daemon=True,
            )
            worker.start()
            self._send_json(job.to_dict(), status=HTTPStatus.ACCEPTED)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)

            if parsed.path == "/":
                self.path = "/index.html"
                return super().do_GET()

            if parsed.path.startswith("/api/jobs/"):
                job_id = parsed.path.rsplit("/", maxsplit=1)[-1]
                job = job_store.get(job_id)
                if job is None:
                    self._send_json({"error": "Job not found."}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(job.to_dict())
                return

            if parsed.path.startswith("/videos/"):
                video_path = settings.videos_dir / parsed.path.split("/videos/", maxsplit=1)[-1]
                if not video_path.exists():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(video_path.stat().st_size))
                self.end_headers()
                with video_path.open("rb") as handle:
                    self.wfile.write(handle.read())
                return

            return super().do_GET()

    return AppHandler


def launch_web_app(settings: Settings, open_browser: bool = True) -> None:
    """Start the local frontend server."""
    handler = build_handler(JobStore(), settings)
    server = ThreadingHTTPServer((settings.frontend_host, settings.frontend_port), handler)
    app_url = f"http://{settings.frontend_host}:{settings.frontend_port}"
    LOGGER.info("Frontend available at %s", app_url)

    if open_browser:
        webbrowser.open(app_url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Shutting down web app.")
    finally:
        server.server_close()
