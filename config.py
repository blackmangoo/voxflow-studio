import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).parent.resolve()
_IS_SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
ACCOUNTS_DIR = Path("/tmp/accounts") if _IS_SERVERLESS else BASE_DIR / "accounts"
PROFILES_DIR = ACCOUNTS_DIR / "browser_profiles"
BRAIN_DIR = BASE_DIR / "brain"
VOICE_DIR = BASE_DIR / "voice"
VIDEO_ENGINE_DIR = BASE_DIR / "video_engine"
COMPOSITOR_DIR = BASE_DIR / "compositor"
OUTPUT_DIR = Path("/tmp/output") if _IS_SERVERLESS else BASE_DIR / "output"
TEMP_DIR = OUTPUT_DIR / "temp"
READY_TO_POST_DIR = OUTPUT_DIR / "ready_to_post"

# Load .env file automatically if present (zero external dependency required)
_ENV_FILE = BASE_DIR / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        _s = _line.strip()
        if _s and not _s.startswith("#") and "=" in _s:
            _k, _v = _s.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# Ensure runtime directories exist (safe on read-only serverless filesystems)
for p in [PROFILES_DIR, TEMP_DIR, READY_TO_POST_DIR]:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

# Google Flow / Multi-Account Worker Pool Settings
# (No personal emails stored in source code — Chrome profiles live locally in accounts/browser_profiles/)
NUM_ACCOUNTS = 6
ACTIVE_ACCOUNTS = ["account_2", "account_3", "account_4", "account_5", "account_6", "account_1"]
ACCOUNT_NAMES = ACTIVE_ACCOUNTS
GOOGLE_FLOW_URL = "https://flow.google.com"

# Video Formatting (Vertical 9:16 for Shorts / TikTok / Reels)
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30

# =============================================================================
# GEMINI TTS API KEY ROTATION POOL  (Loaded from .env — never hardcoded)
# =============================================================================
_raw_tts_keys = os.environ.get("GEMINI_TTS_KEYS", "")
GEMINI_TTS_KEYS = [k.strip() for k in _raw_tts_keys.split(",") if k.strip()]

# Fallback Edge-TTS Settings
DEFAULT_VOICE = "en-US-ChristopherNeural"
VOICE_RATE = "+5%"
VOICE_PITCH = "+0Hz"

# ---------------------------------------------------------------------------
# Per-channel subtitle brand identity
# ASS color format: &HAABBGGRR  (alpha, blue, green, red — all hex)
# ---------------------------------------------------------------------------
CHANNEL_SUBTITLE_CONFIGS = {
    "body_simulator": {
        "font": "Arial Black", "size": 76,
        "primary": "&H00FFFFFF",
        "highlight": "&H0000FFFF",
        "outline": "&H00000000",
        "outline_w": 8.0, "shadow": 4.0,
    },
    "xray_mechanics": {
        "font": "Arial Black", "size": 72,
        "primary": "&H00E0E0E0",
        "highlight": "&H00FFFF00",
        "outline": "&H00000000",
        "outline_w": 7.0, "shadow": 3.0,
    },
    "crazy_characters": {
        "font": "Impact", "size": 80,
        "primary": "&H00FFFFFF",
        "highlight": "&H000080FF",
        "outline": "&H00000000",
        "outline_w": 9.0, "shadow": 4.0,
    },
    "health_coach": {
        "font": "Arial Black", "size": 70,
        "primary": "&H00FFFFFF",
        "highlight": "&H0000C000",
        "outline": "&H00000000",
        "outline_w": 7.0, "shadow": 3.0,
    },
    "garage_guru": {
        "font": "Impact", "size": 76,
        "primary": "&H00FFFFFF",
        "highlight": "&H000066FF",
        "outline": "&H00000000",
        "outline_w": 8.0, "shadow": 3.5,
    },
    "code_classroom": {
        "font": "Courier New", "size": 68,
        "primary": "&H00D0FFD0",
        "highlight": "&H0000FF00",
        "outline": "&H00000000",
        "outline_w": 6.0, "shadow": 3.0,
    },
}

SUBTITLE_CONFIG_DEFAULT = {
    "font": "Arial Black", "size": 76,
    "primary": "&H00FFFFFF",
    "highlight": "&H0000FFFF",
    "outline": "&H00000000",
    "outline_w": 8.0, "shadow": 4.0,
}

GLOBAL_STYLE_DNA = (
    "cinematic 9:16 vertical video, hyper-saturated vivid neon color palette, "
    "electric cyan and vibrant magenta rim lighting, volumetric fog, "
    "high dynamic range, glossy surfaces, ultra-detailed 8k, photorealistic rendering"
)
