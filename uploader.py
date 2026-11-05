import os
import sys
import datetime
from pathlib import Path

# Try to import Google API libs
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    GOOGLE_LIBS_INSTALLED = True
except ImportError:
    GOOGLE_LIBS_INSTALLED = False

# Scopes needed for YouTube Data API
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def authenticate_youtube(channel: str):
    """
    Authenticates with YouTube API. Saves a specific token per channel.
    """
    creds = None
    token_file = f"token_{channel}.json"

    if os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        except Exception:
            pass

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            if not os.path.exists("client_secrets.json"):
                print("    ⚠️ [YOUTUBE] SKIPPED: No 'client_secrets.json' found.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_file, "w") as token:
            token.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(video_path: str, title: str, description: str, tags: list, channel_name: str):
    """
    Uploads a short to YouTube automatically.
    """
    print(f"\n🚀 [YOUTUBE UPLOAD] Preparing upload for {channel_name}...")
    print(f"   📺 Title: {title}")

    if not GOOGLE_LIBS_INSTALLED:
        print("   ⚠️ [YOUTUBE] SKIPPED: Missing libraries. Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
        return False

    youtube = authenticate_youtube(channel_name)
    if not youtube:
        return False

    try:
        request_body = {
            "snippet": {
                "title": title[:100],  # YT limit
                "description": description,
                "tags": tags,
                "categoryId": "22"  # 22 is Entertainment, 27 is Education, 23 is Comedy
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }

        media_file = MediaFileUpload(video_path, chunksize=-1, resumable=True)

        print("   ⏳ Uploading video file...")
        request = youtube.videos().insert(
            part="snippet,status",
            body=request_body,
            media_body=media_file
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"   ⏳ Upload progress: {int(status.progress() * 100)}%")

        print(f"   ✅ SUCCESS! Video published at: https://youtube.com/shorts/{response['id']}")
        return True

    except Exception as e:
        print(f"   ❌ [YOUTUBE] Error during upload: {e}")
        return False


def upload_to_tiktok(video_path: str, title: str, channel_name: str):
    """
    Simulated TikTok upload. TikTok's direct publishing API requires business registration.
    """
    print(f"🚀 [TIKTOK UPLOAD] Simulated upload for {channel_name}... (Business API required)")
    return True
