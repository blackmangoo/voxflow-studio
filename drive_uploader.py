"""
drive_uploader.py — Google Drive upload pipeline for the AI video automation system.

Auth: OAuth via client_secrets.json (same pattern as uploader.py).
      Scope: drive.file — app can only see files/folders it created itself.
      Token: token_drive.json — saved after first browser consent, silent forever after.

First run only:
    python drive_uploader.py
    → Browser opens → log into your Google account → Allow Drive access
    → token_drive.json saved — never asked again

Folder structure created inside your Drive root folder:
    [DRIVE_ROOT_FOLDER_ID]/
    └── {channel}/
        └── {YYYY-MM-DD}_{concept_slug}_{lang}/
            ├── video.mp4
            ├── thumbnail.jpg
            └── metadata.txt
"""

import io
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# drive.file — app can only touch files/folders it created. Safe and minimal.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_FILE = ROOT_DIR / "token_drive.json"
CLIENT_SECRETS = ROOT_DIR / "client_secrets.json"

# Your Drive root folder — channel subfolders are created directly inside this.
# https://drive.google.com/drive/folders/1hP0Drmnq4GzM4IcxzU1ub_ar0T6KAGCa
DRIVE_ROOT_FOLDER_ID = "1hP0Drmnq4GzM4IcxzU1ub_ar0T6KAGCa"


# ─────────────────────────────────────────────────────────────────────────────
# Auth — identical pattern to uploader.py
# ─────────────────────────────────────────────────────────────────────────────

def _authenticate(interactive: bool = False) -> object:
    """
    OAuth via client_secrets.json. First run (`python drive_uploader.py`) opens browser;
    automated pipeline runs (`interactive=False`) use token_drive.json silently and
    fail fast if missing/revoked instead of blocking headless servers on run_local_server().
    """
    creds = None

    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            if not interactive:
                raise RuntimeError(
                    "token_drive.json missing or expired — skipping Drive upload in non-interactive server mode "
                    "(run 'python drive_uploader.py' once in terminal to re-authorize)."
                )
            if not CLIENT_SECRETS.exists():
                raise FileNotFoundError(
                    f"client_secrets.json not found at {CLIENT_SECRETS}\n"
                    "Download it from Google Cloud Console → APIs & Services → Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        print(f"    [Drive] Token saved → {TOKEN_FILE.name}")

    return build("drive", "v3", credentials=creds)


# ─────────────────────────────────────────────────────────────────────────────
# Folder helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_folder(service, name: str, parent_id: str) -> Optional[str]:
    """
    Searches Drive for a folder with `name` under `parent_id`.
    drive.file scope only returns folders the app itself created — which is
    exactly what we want (channel + episode folders the app manages).
    """
    q = (
        f"mimeType='application/vnd.google-apps.folder'"
        f" and name='{name}'"
        f" and '{parent_id}' in parents"
        f" and trashed=false"
    )
    results = service.files().list(
        q=q,
        spaces="drive",
        fields="files(id)",
        pageSize=1,
    ).execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None


def _create_folder(service, name: str, parent_id: str) -> str:
    """Creates a folder under parent_id and returns its id."""
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    """Returns existing folder id or creates a new one."""
    existing = _find_folder(service, name, parent_id)
    return existing if existing else _create_folder(service, name, parent_id)


# ─────────────────────────────────────────────────────────────────────────────
# Thumbnail
# ─────────────────────────────────────────────────────────────────────────────

def _extract_thumbnail(video_path: Path, output_path: Path) -> Optional[Path]:
    """Grabs the frame at 1s from the video using ffmpeg."""
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", "1", "-i", str(video_path),
                "-vframes", "1", "-q:v", "2", "-vf", "scale=1080:1920",
                str(output_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return output_path if output_path.exists() else None
    except Exception as e:
        print(f"    [Drive] Thumbnail extraction failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Upload helpers
# ─────────────────────────────────────────────────────────────────────────────

def _upload_file(service, local_path: Path, drive_name: str, parent_id: str, mimetype: str) -> str:
    """Uploads a local file to Drive. Returns the Drive file id."""
    media = MediaFileUpload(str(local_path), mimetype=mimetype, resumable=True)
    result = service.files().create(
        body={"name": drive_name, "parents": [parent_id]},
        media_body=media,
        fields="id",
    ).execute()
    return result["id"]


def _upload_bytes(service, content: bytes, drive_name: str, parent_id: str, mimetype: str) -> str:
    """Uploads in-memory bytes to Drive. Returns the Drive file id."""
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mimetype, resumable=False)
    result = service.files().create(
        body={"name": drive_name, "parents": [parent_id]},
        media_body=media,
        fields="id",
    ).execute()
    return result["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def upload_video_package(
    channel: str,
    concept: str,
    video_path: Path,
    title: str,
    caption: str,
    hashtags: list,
    thumbnail_path: Optional[Path] = None,
    lang: str = "english",
) -> dict:
    """
    Uploads video + thumbnail + metadata.txt into a dated episode folder
    inside DRIVE_ROOT_FOLDER_ID/{channel}/.

    Returns:
        {
            "folder_url": "https://drive.google.com/drive/folders/<id>",
            "folder_id": "<episode folder id>",
            "video_id":  "<video file id>",
        }
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    print(f"\n    [Drive] Authenticating...")
    service = _authenticate()

    # ── Folder tree: root (pre-existing) → channel → episode ─────────────────
    print(f"    [Drive] Resolving folder tree...")
    channel_id = _get_or_create_folder(service, channel, DRIVE_ROOT_FOLDER_ID)

    date_str = date.today().isoformat()
    concept_slug = (
        "".join(c if c.isalnum() or c in (" ", "_") else "" for c in concept)
        .strip().replace(" ", "_").lower()[:40]
    )
    episode_folder_name = f"{date_str}_{concept_slug}_{lang}"
    episode_id = _get_or_create_folder(service, episode_folder_name, channel_id)

    # Auto-share: anyone with the link can view — no manual share step needed
    try:
        service.permissions().create(
            fileId=episode_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
        ).execute()
    except Exception as e:
        print(f"    [Drive] Auto-share warning: {e}")

    folder_url = f"https://drive.google.com/drive/folders/{episode_id}"
    print(f"    [Drive] Episode folder (public link): {folder_url}")

    # ── video.mp4 ─────────────────────────────────────────────────────────────
    size_mb = video_path.stat().st_size // 1_000_000
    print(f"    [Drive] Uploading video ({size_mb} MB)...")
    video_id = _upload_file(service, video_path, "video.mp4", episode_id, "video/mp4")
    print(f"    [Drive] Video uploaded")

    # ── thumbnail.jpg ─────────────────────────────────────────────────────────
    thumb = thumbnail_path and Path(thumbnail_path)
    if not thumb or not thumb.exists():
        thumb = _extract_thumbnail(video_path, video_path.with_suffix(".thumb.jpg"))

    if thumb and thumb.exists():
        _upload_file(service, thumb, "thumbnail.jpg", episode_id, "image/jpeg")
        print(f"    [Drive] Thumbnail uploaded")
    else:
        print(f"    [Drive] Thumbnail skipped")

    # ── metadata.txt ──────────────────────────────────────────────────────────
    meta = (
        f"TITLE:\n{title}\n\n"
        f"CAPTION:\n{caption}\n\n"
        f"HASHTAGS:\n{' '.join(hashtags)}\n\n"
        f"CHANNEL: {channel}\n"
        f"LANGUAGE: {lang}\n"
        f"DATE: {date_str}\n"
        f"DRIVE FOLDER: {folder_url}\n"
    )
    _upload_bytes(service, meta.encode("utf-8"), "metadata.txt", episode_id, "text/plain")
    print(f"    [Drive] Metadata uploaded")

    return {
        "folder_url": folder_url,
        "folder_id": episode_id,
        "video_id": video_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# First-run OAuth setup — python drive_uploader.py
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Drive OAuth first-run setup...")
    svc = _authenticate(interactive=True)
    print(f"Authenticated. Token saved to: {TOKEN_FILE.name}")
    print(f"Drive uploader ready — uploads go to folder: {DRIVE_ROOT_FOLDER_ID}")
