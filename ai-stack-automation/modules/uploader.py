"""Upload generated videos to YouTube."""

from __future__ import annotations

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from config.settings import Settings


LOGGER = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _get_authenticated_service(settings: Settings):
    """Authenticate with YouTube and return an API client."""
    if not settings.youtube_client_secrets_file:
        raise ValueError("YOUTUBE_CLIENT_SECRETS_FILE is not set in the environment.")

    secrets_file = Path(settings.youtube_client_secrets_file)
    if not secrets_file.exists():
        raise FileNotFoundError(f"YouTube client secrets file not found: {secrets_file}")

    credentials = None
    token_file = Path(settings.youtube_token_file)

    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_file), SCOPES)
        credentials = flow.run_local_server(port=0)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(credentials.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=credentials)


def upload_video(
    video_file: str,
    title: str,
    description: str,
    tags: list[str],
    thumbnail_file: str | None,
    settings: Settings,
) -> dict:
    """Upload the generated video and optionally set the thumbnail."""
    video_path = Path(video_file)
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    youtube = _get_authenticated_service(settings)
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": settings.youtube_category_id,
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)

    try:
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        response = request.execute()

        if thumbnail_file and Path(thumbnail_file).exists():
            try:
                youtube.thumbnails().set(
                    videoId=response["id"],
                    media_body=MediaFileUpload(thumbnail_file),
                ).execute()
            except HttpError as exc:
                LOGGER.warning(
                    "Video uploaded, but thumbnail upload was skipped: %s",
                    exc,
                )

        LOGGER.info("YouTube video uploaded with ID: %s", response["id"])
        return response
    except HttpError as exc:
        LOGGER.exception("YouTube upload failed.")
        raise RuntimeError(f"Failed to upload video to YouTube: {exc}") from exc
