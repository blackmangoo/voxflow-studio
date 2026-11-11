import asyncio
import collections
import hashlib
import json
import math
import os
import secrets
import struct
import sys
import threading
import time
import urllib.parse
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config  # loads .env into os.environ
from brain.multi_channel_director import MultiChannelDirector
from config import OUTPUT_DIR
from voice.voxstudio_engine import VOICE_CONFIGS, VoxStudioEngine
from saas_store import (
    CHANNEL_CATALOG,
    PRICING_PLANS,
    VISUAL_STYLE_CATALOG,
    calculate_pricing_comparison,
    create_checkout_lead,
    create_job_record,
    create_series_record,
    delete_checkout_lead,
    delete_series_record,
    discover_rendered_vault,
    get_account_pool_telemetry,
    init_db,
    init_saas_db,
    list_checkout_leads,
    list_job_records,
    list_series_records,
    normalize_plan_tier,
    reconcile_stale_jobs,
    update_job_record,
    update_series_status_record,
    upload_video_to_supabase_cdn,
)

NICHE_NAMES = {ch["id"]: ch["id"] for ch in CHANNEL_CATALOG}

app = FastAPI(
    title="VoxFlow Studio — Autonomous 3D Video SaaS API",
    description="Multi-Channel 3D Animated Shorts Autopilot with Dual-Language (English + Urdu/Hindi) Arbitrage & Custom AI Director.",
    version="3.0.0",
)

# Strict CORS Origin Pinning from .env
_allowed_origins = [
    o.strip()
    for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Studio-Key"],
)

init_saas_db()
reconcile_stale_jobs()

STUDIO_ADMIN_KEY = os.environ.get("STUDIO_ADMIN_KEY") or os.environ.get("AGENT_API_KEY") or ""
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_PROJECT_REF = os.environ.get("SUPABASE_PROJECT_REF", "ouqjlqqgnboytjvudylv")

SAAS_WEB_DIR = ROOT_DIR / "saas_web"

# Concurrency lock: at most 1 active real Playwright/TTS pipeline job at a time
_pipeline_semaphore = asyncio.Semaphore(1)
_cancelled_jobs: set = set()
_active_job_threads: Dict[str, Any] = {}

# Thread-local HTTP Keep-Alive session to Supabase (avoids TLS handshakes while staying thread-safe)
_thread_local = threading.local()


def _get_http_session() -> requests.Session:
    sess = getattr(_thread_local, "session", None)
    if sess is None:
        sess = requests.Session()
        _thread_local.session = sess
    return sess


_jwt_profile_cache: Dict[str, Any] = {}
JWT_CACHE_TTL_SECONDS = 30.0

# Sliding-window IP rate limiter for POST mutations (max 15 requests / 60s per IP)
_ip_request_log: Dict[str, collections.deque] = collections.defaultdict(collections.deque)
RATE_LIMIT_MAX_REQUESTS = 15
RATE_LIMIT_WINDOW_SECONDS = 60.0


@app.middleware("http")
async def security_headers_and_rate_limit(request: Request, call_next):
    if request.method == "POST":
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        dq = _ip_request_log[client_ip]
        while dq and (now - dq[0]) > RATE_LIMIT_WINDOW_SECONDS:
            dq.popleft()
        if len(dq) >= RATE_LIMIT_MAX_REQUESTS:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please wait 60 seconds before submitting again."},
            )
        dq.append(now)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def _is_authorized_studio_key(request: Request) -> bool:
    """Constant-time check for X-Studio-Key or Authorization: Bearer <STUDIO_ADMIN_KEY>."""
    header_key = (request.headers.get("X-Studio-Key") or "").strip()
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not header_key and auth_header.lower().startswith("bearer "):
        candidate = auth_header[7:].strip()
        if candidate and secrets.compare_digest(candidate.encode("utf-8"), STUDIO_ADMIN_KEY.encode("utf-8")):
            return True
    if not header_key or not STUDIO_ADMIN_KEY:
        return False
    return secrets.compare_digest(header_key.encode("utf-8"), STUDIO_ADMIN_KEY.encode("utf-8"))


def _verify_supabase_user_token(request: Request) -> Optional[Dict[str, Any]]:
    """
    Verifies a Supabase Auth JWT from Authorization: Bearer <jwt> against the
    dedicated voxflow-studio Supabase instance and loads the user's profile
    (role, plan_tier, credits_balance, sandbox_runs_remaining).
    """
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header.lower().startswith("bearer "):
        return None
    jwt_token = auth_header[7:].strip()
    # Skip if it's the static STUDIO_ADMIN_KEY
    if not jwt_token or jwt_token.startswith("vf_admin_"):
        return None
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None

    now = time.time()
    cached = _jwt_profile_cache.get(jwt_token)
    if cached and (now - cached[0]) < JWT_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        sess = _get_http_session()
        user_resp = sess.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {jwt_token}",
            },
            timeout=6,
        )
        if user_resp.status_code != 200:
            return None
        user_data = user_resp.json()
        user_id = user_data.get("id")
        email = (user_data.get("email") or "").lower()
        if not user_id:
            return None

        # Fetch profile via RLS using user's JWT
        enc_uid = urllib.parse.quote(str(user_id), safe="")
        prof_resp = sess.get(
            f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{enc_uid}&select=*",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {jwt_token}",
            },
            timeout=6,
        )
        if prof_resp.status_code == 200 and prof_resp.json():
            prof = prof_resp.json()[0]
            role_val = prof.get("role", "user")
            if role_val == "admin":
                pool_tel = get_account_pool_telemetry()
                real_tokens = int(pool_tel.get("cluster_tokens_remaining", 0))
                real_episodes = int(pool_tel.get("cluster_episodes_remaining", real_tokens // 40))
            else:
                real_tokens = int(prof.get("credits_balance", 0))
                real_episodes = int(prof.get("sandbox_runs_remaining", 5))
            res_obj = {
                "id": user_id,
                "email": email,
                "role": role_val,
                "plan_tier": prof.get("plan_tier", "free"),
                "credits_balance": real_tokens,
                "sandbox_runs_remaining": real_episodes,
                "wa_agent_token": prof.get("wa_agent_token", ""),
                "wa_user_id": prof.get("wa_user_id", ""),
                "wa_verified": bool(prof.get("wa_verified", False)),
                "jwt": jwt_token,
            }
            _jwt_profile_cache[jwt_token] = (now, res_obj)
            return res_obj
        is_owner = email in ("ammar.akbar2002@gmail.com", "ammar.akbar2069@gmail.com")
        pool_tel = get_account_pool_telemetry() if is_owner else {}
        owner_tokens = int(pool_tel.get("cluster_tokens_remaining", 0))
        owner_episodes = int(pool_tel.get("cluster_episodes_remaining", owner_tokens // 40))
        res_obj = {
            "id": user_id,
            "email": email,
            "role": "admin" if is_owner else "user",
            "plan_tier": "both_daily" if is_owner else "free",
            "credits_balance": owner_tokens if is_owner else 0,
            "sandbox_runs_remaining": owner_episodes if is_owner else 5,
            "jwt": jwt_token,
        }
        _jwt_profile_cache[jwt_token] = (now, res_obj)
        return res_obj
    except Exception:
        return None


def _extract_request_auth(request: Request) -> Dict[str, Any]:
    if _is_authorized_studio_key(request):
        return {"role": "admin", "mode": "studio_key"}
    sb_user = _verify_supabase_user_token(request)
    return sb_user or {}


def _resolve_caller_authorization(request: Request) -> Dict[str, Any]:
    """
    Determines caller privilege level:
      - can_live_render: True only if caller holds STUDIO_ADMIN_KEY OR is a Supabase
        authenticated user with role == 'admin' or credits_balance > 0.
      - is_authenticated: True if caller holds STUDIO_ADMIN_KEY or a valid Supabase session.
    """
    has_studio_key = _is_authorized_studio_key(request)
    sb_user = _verify_supabase_user_token(request)

    if has_studio_key:
        return {
            "is_authenticated": True,
            "can_live_render": True,
            "mode": "studio_key",
            "user": sb_user,
        }

    if sb_user:
        can_live = sb_user.get("role") == "admin" or sb_user.get("credits_balance", 0) > 0
        return {
            "is_authenticated": True,
            "can_live_render": can_live,
            "mode": "supabase_jwt",
            "user": sb_user,
        }

    return {
        "is_authenticated": False,
        "can_live_render": False,
        "mode": "anonymous",
        "user": None,
    }


async def verify_api_key(request: Request):
    auth = _resolve_caller_authorization(request)
    if not auth["can_live_render"]:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Valid Studio Admin Key or Admin/Credited Supabase Account required.",
        )


# ─── Pydantic Contracts ──────────────────────────────────────────────────────

class ManualSceneItem(BaseModel):
    flow_prompt: str = Field(..., min_length=3, max_length=700, description="3D camera & motion prompt for 10s shot")
    speaker: str = Field("narrator", max_length=40)
    english_line: str = Field("", max_length=280)
    urdu_line: str = Field("", max_length=280)


class DirectorPreviewRequest(BaseModel):
    creation_mode: str = Field("custom_director", pattern="^(prebuilt|custom_director|manual_scenes)$")
    channel: str = Field("body_simulator", description="Base show persona/voice configuration")
    custom_prompt: str = Field("", max_length=1000, description="User's custom story idea, topic, or hook")
    visual_style: str = Field("pixar_3d", max_length=400, description="Preset ID or custom 3D style DNA")
    custom_scenes: Optional[List[ManualSceneItem]] = Field(None, description="Optional manual 4-scene override")


class SeriesCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80, description="Series title")
    channel: str = Field(..., description="One of the 6 show formats")
    language_tier: str = Field(..., pattern="^(urdu|english|both)$")
    plan_id: Optional[str] = Field(None, description="Optional specific plan_id")
    creation_mode: str = Field("prebuilt", pattern="^(prebuilt|custom_director|manual_scenes)$")
    custom_prompt: str = Field("", max_length=1000)
    visual_style: str = Field("pixar_3d", max_length=400)


class GenerateEpisodeRequest(BaseModel):
    channel: str = Field("body_simulator", description="Target show channel")
    lang: str = Field("both", pattern="^(urdu|english|both)$")
    mock: bool = Field(False, description="False for live Google Flow render, True for simulation")
    scenes: Optional[int] = Field(None, ge=1, le=4)
    series_id: Optional[str] = None
    creation_mode: str = Field("prebuilt", pattern="^(prebuilt|custom_director|manual_scenes)$")
    custom_prompt: str = Field("", max_length=1000, description="Custom user prompt / episode concept")
    visual_style: str = Field("pixar_3d", max_length=400, description="Visual style preset or custom style DNA")
    custom_scenes: Optional[List[ManualSceneItem]] = Field(None, description="Manual scene-by-scene overrides")


class VoicePreviewRequest(BaseModel):
    voice_id: str = Field("Charon", description="Voice persona: Charon, Kore, Puck, Fenrir, Aoede")
    channel: str = Field("body_simulator")
    lang: str = Field("english", pattern="^(english|urdu)$")
    text: Optional[str] = Field(None, max_length=280)


class ProvisionCustomerRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120, description="Customer login email")
    password: str = Field(..., min_length=6, max_length=100, description="Password to issue to the customer")
    full_name: str = Field("", max_length=80, description="Customer or channel name")
    plan_tier: str = Field(
        "both_daily",
        pattern="^(starter|daily|urdu_starter|urdu_daily|english_starter|english_daily|both_starter|both_daily)$",
    )
    credits_balance: Optional[int] = Field(None, ge=0, le=10000, description="Override credits (defaults to plan episodes)")


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120, description="Registered account email")
    redirect_to: Optional[str] = Field(None, max_length=300, description="Optional password reset redirect URL")


class TrialSignupRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120, description="New creator email address")
    password: str = Field(..., min_length=6, max_length=100, description="Account password")
    full_name: str = Field("", max_length=80, description="Creator or channel name")


class CheckoutLeadRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120, description="Buyer email address")
    whatsapp: str = Field("", max_length=60, description="Buyer WhatsApp number")
    plan_tier: str = Field(
        "both_daily",
        pattern="^(starter|daily|urdu_starter|urdu_daily|english_starter|english_daily|both_starter|both_daily)$",
    )
    payment_method: str = Field("whatsapp_concierge", max_length=60)
    notes: str = Field("", max_length=600)


class SeriesStatusUpdateRequest(BaseModel):
    status: Optional[str] = Field(None, pattern="^(active|paused)$")


class WhatsAppTestRequest(BaseModel):
    wa_agent_token: str = Field(..., min_length=6, max_length=600, description="User's personal WhatsApp Agent API Token")
    wa_user_id: str = Field(..., min_length=3, max_length=120, description="User's personal WhatsApp User ID or Phone Number")


class WhatsAppConfirmRequest(BaseModel):
    received: bool = Field(..., description="True if the user confirmed receiving the test message on their phone")


class PoolTokenAdjustmentRequest(BaseModel):
    account_name: str = Field(..., description="Target account identifier, e.g. account_2 or node_1")
    tokens_remaining: int = Field(..., ge=0, description="Calibrated Flow generation tokens remaining")
    tokens_total: Optional[int] = Field(1000, ge=1, description="Total monthly token allotment")


class TriggerResponse(BaseModel):
    status: str
    message: str
    job_id: str
    niche: str


# ─── Background Pipeline Runners ─────────────────────────────────────────────

async def _execute_sandbox_demo_job(
    job_id: str,
    channel: str,
    lang: str,
    creation_mode: str = "prebuilt",
    custom_prompt: str = "",
    visual_style: str = "pixar_3d",
) -> None:
    """
    Zero-API, Zero-Playwright public sandbox simulation.
    Used when an unauthenticated visitor or free-tier user tests the UI in mock mode
    so ZERO Google Flow credits and ZERO Chrome browser processes are touched.
    """
    mode_tag = (
        f"Custom Prompt ('{custom_prompt[:36]}...')"
        if creation_mode == "custom_director" and custom_prompt
        else ("Manual 4-Scene Matrix" if creation_mode == "manual_scenes" else f"Show '{channel}'")
    )
    stages = [
        (20, f"[1/6] Sandbox Director: Compiling 4-scene storyboard for {mode_tag}..."),
        (45, f"[2/6] Sandbox Engine: Simulating 4× 10s 3D shots ({visual_style}) — 0 Flow credits used..."),
        (65, "[3/6] Sandbox Vision Gate: Verifying motion vectors & frame sharpness..."),
        (82, f"[4/6] Sandbox Audio: Simulating {lang.upper()} neural voice acting & -18dB ducking..."),
        (100, "[6/6] Sandbox Simulation Complete — Unlock Live Credits or Admin Key for Google Flow 3D Render"),
    ]
    for prog, label in stages:
        await asyncio.sleep(0.45)
        update_job_record(
            job_id,
            status="completed" if prog == 100 else "running",
            stage=label,
            progress=prog,
        )


def _patch_supabase_job_by_code(job_id: str, **fields) -> None:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return
    try:
        payload = {**fields, "updated_at": datetime.now(timezone.utc).isoformat()}
        enc_code = urllib.parse.quote(str(job_id), safe="")
        _get_http_session().patch(
            f"{SUPABASE_URL}/rest/v1/render_jobs?job_code=eq.{enc_code}",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=6,
        )
    except Exception:
        pass


def _run_pipeline_in_proactor_loop(target, *args, job_id: str = "", **kwargs):
    """
    Executes the async Playwright + TTS + FFmpeg pipeline in a dedicated worker thread
    backed by an explicit Windows ProactorEventLoop, supporting live cancellation via _active_job_threads.
    """
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        coro = target(*args, **kwargs) if callable(target) else target
        main_task = loop.create_task(coro)
        if job_id:
            _active_job_threads[job_id] = (loop, main_task)
        return loop.run_until_complete(main_task)
    finally:
        if job_id:
            _active_job_threads.pop(job_id, None)
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


async def _execute_episode_job(
    job_id: str,
    channel: str,
    lang: str,
    mock: bool,
    scenes: Optional[int],
    creation_mode: str = "prebuilt",
    custom_prompt: str = "",
    visual_style: str = "pixar_3d",
    custom_scenes: Optional[List[Dict[str, Any]]] = None,
    wa_token: str = "",
    wa_user_id: str = "",
    allow_owner_wa_fallback: bool = False,
) -> None:
    """
    Authenticated production execution runner (protected by _pipeline_semaphore).
    Only callable when verified by STUDIO_ADMIN_KEY or credited Supabase account.
    """
    if job_id in _cancelled_jobs:
        return

    if _pipeline_semaphore.locked():
        update_job_record(
            job_id,
            status="queued",
            stage="[0/6] Waiting for active Playwright/TTS job to finish...",
            progress=10,
        )

    async with _pipeline_semaphore:
        if job_id in _cancelled_jobs:
            return
        try:
            init_stage = f"[1/6] AI Director ({creation_mode}): Compiling 4-scene script & shot directives..."
            update_job_record(job_id, status="running", stage=init_stage, progress=20)
            await asyncio.to_thread(_patch_supabase_job_by_code, job_id, status="running", stage=init_stage, progress=20)
            await asyncio.sleep(0.2)

            def _progress_cb(stage: str, progress: int, concept: str = None, script_preview: dict = None):
                if job_id in _cancelled_jobs:
                    raise asyncio.CancelledError("Render cancelled by user")
                fields: Dict[str, Any] = {"status": "running", "stage": stage, "progress": progress}
                sb_fields: Dict[str, Any] = {"status": "running", "stage": stage, "progress": progress}
                if concept:
                    fields["concept"] = concept[:160]
                    sb_fields["concept"] = concept[:160]
                if script_preview:
                    fields["script_preview"] = json.dumps(script_preview, ensure_ascii=False)
                    sb_fields["script_preview"] = script_preview
                update_job_record(job_id, **fields)
                _patch_supabase_job_by_code(job_id, **sb_fields)

            if os.environ.get("VERCEL"):
                update_job_record(
                    job_id,
                    status="queued",
                    stage="[1/6] Queued in Supabase — Awaiting Local Flow Worker Cluster Claim...",
                    progress=25,
                )
                return

            from multi_channel_agent import produce_dual_language_episode

            urdu_final, english_final = await asyncio.to_thread(
                _run_pipeline_in_proactor_loop,
                produce_dual_language_episode,
                job_id=job_id,
                channel=channel,
                mock_video=mock,
                max_scenes=scenes,
                target_lang=lang,
                custom_prompt=custom_prompt if creation_mode in ("custom_director", "manual_scenes") else None,
                visual_style=visual_style,
                custom_scenes=custom_scenes if creation_mode == "manual_scenes" else None,
                progress_callback=_progress_cb,
                wa_token=wa_token,
                wa_user_id=wa_user_id,
                allow_owner_wa_fallback=allow_owner_wa_fallback,
            )

            if job_id in _cancelled_jobs:
                return

            en_url = f"/media/{channel}/english/{Path(english_final).name}" if english_final else ""
            ur_url = f"/media/{channel}/urdu/{Path(urdu_final).name}" if urdu_final else ""
            cdn_en = (
                await asyncio.to_thread(upload_video_to_supabase_cdn, Path(english_final), channel, "english")
                if english_final
                else ""
            )
            cdn_ur = (
                await asyncio.to_thread(upload_video_to_supabase_cdn, Path(urdu_final), channel, "urdu")
                if urdu_final
                else ""
            )

            update_job_record(
                job_id,
                status="completed",
                stage="[6/6] Completed — Synced, Ducked & Exported",
                progress=100,
                english_video=en_url or cdn_en,
                urdu_video=ur_url or cdn_ur,
            )
            await asyncio.to_thread(
                _patch_supabase_job_by_code,
                job_id,
                status="completed",
                stage="[6/6] Completed — Synced, Ducked & Exported",
                progress=100,
                english_video=cdn_en or en_url,
                urdu_video=cdn_ur or ur_url,
            )
        except asyncio.CancelledError:
            update_job_record(
                job_id,
                status="cancelled",
                stage="Cancelled by user",
                error="",
            )
            await asyncio.to_thread(
                _patch_supabase_job_by_code,
                job_id,
                status="cancelled",
                stage="Cancelled by user",
                error="",
            )
        except Exception as e:
            if job_id in _cancelled_jobs:
                return
            err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            update_job_record(
                job_id,
                status="failed",
                stage="Pipeline halted with error",
                error=err_msg[:240],
            )
            await asyncio.to_thread(
                _patch_supabase_job_by_code,
                job_id,
                status="failed",
                stage="Pipeline halted with error",
                error=err_msg[:240],
            )


# ─── Public Web UI & Media Streaming ─────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, tags=["Web UI"])
async def serve_saas_app():
    index_file = SAAS_WEB_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>VoxFlow SaaS UI building...</h1>", status_code=200)
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get("/media/{channel}/{lang}/{filename}", tags=["Media"])
async def stream_rendered_media(channel: str, lang: str, filename: str):
    if channel not in NICHE_NAMES or lang not in ("english", "urdu"):
        raise HTTPException(status_code=400, detail="Invalid channel or language segment")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    target = (OUTPUT_DIR / channel / lang / filename).resolve()
    allowed_root = (OUTPUT_DIR / channel / lang).resolve()
    if not str(target).startswith(str(allowed_root)) or not target.exists():
        raise HTTPException(status_code=404, detail="Media file not found")

    media_type = "video/mp4" if filename.endswith(".mp4") else "image/jpeg"
    return FileResponse(str(target), media_type=media_type)


# ─── SaaS Platform REST API ──────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "VoxFlow Studio SaaS API",
        "security_mode": "hardened_supabase_rls",
        "supabase_project_ref": SUPABASE_PROJECT_REF,
    }


@app.get("/api/config/public", tags=["SaaS"])
async def get_public_config():
    """
    Returns ONLY public client configuration safe for browser consumption:
    Supabase URL, public Anon Key (protected by PostgreSQL RLS), and Visual Style Presets.
    NEVER exposes SUPABASE_SERVICE_ROLE_KEY, STUDIO_ADMIN_KEY, or GEMINI_TTS_KEYS.
    """
    return {
        "supabase_url": SUPABASE_URL,
        "supabase_anon_key": SUPABASE_ANON_KEY,
        "supabase_project_ref": SUPABASE_PROJECT_REF,
        "visual_style_presets": VISUAL_STYLE_CATALOG,
        "public_demo_mode": True,
    }


@app.get("/api/catalog", tags=["SaaS"])
async def get_saas_catalog(request: Request):
    is_admin = _is_authorized_studio_key(request) or _extract_request_auth(request).get("role") == "admin"
    return {
        "channels": CHANNEL_CATALOG,
        "visual_styles": VISUAL_STYLE_CATALOG,
        "plans": list(PRICING_PLANS.values()),
        "pool": get_account_pool_telemetry() if is_admin else [],
    }


@app.post("/api/auth/forgot-password", tags=["Auth"])
async def api_forgot_password(req: ForgotPasswordRequest):
    """
    Triggers a Supabase Auth password recovery email for the user.
    """
    clean_email = req.email.strip().lower()
    if "@" not in clean_email or "." not in clean_email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(status_code=500, detail="Supabase authentication is not configured.")

    recover_url = f"{SUPABASE_URL}/auth/v1/recover"
    if req.redirect_to:
        enc_redir = urllib.parse.quote(req.redirect_to.strip(), safe="")
        recover_url = f"{recover_url}?redirect_to={enc_redir}"

    def _recover_sync():
        return _get_http_session().post(
            recover_url,
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Content-Type": "application/json",
            },
            json={"email": clean_email},
            timeout=10,
        )

    resp = await asyncio.to_thread(_recover_sync)
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=400,
            detail=f"Password recovery request failed: {resp.text[:180]}",
        )
    return {
        "status": "ok",
        "message": "If an account exists for that email, a password reset link has been sent.",
    }


@app.post("/api/auth/trial-signup", tags=["Auth"])
async def api_trial_signup(req: TrialSignupRequest):
    """
    Self-serve Free Trial Signup (Debate 3 Option B):
    Creates a confirmed user account with role='user', plan_tier='both_starter',
    credits_balance=0, and sandbox_runs_remaining=3 so new creators can immediately
    sign in, test the AI Director Storyboard Preview and 3 Sandbox simulations,
    and hit the upgrade gate when attempting a Live 3D render.
    """
    clean_email = req.email.strip().lower()
    if "@" not in clean_email or "." not in clean_email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    if not SUPABASE_URL or not (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY):
        raise HTTPException(status_code=500, detail="Supabase authentication is not configured.")

    clean_name = req.full_name.strip() or clean_email.split("@")[0]

    def _signup_sync() -> Dict[str, Any]:
        sess = _get_http_session()
        encoded_email = urllib.parse.quote(clean_email, safe="")

        if SUPABASE_SERVICE_ROLE_KEY:
            srk_headers = {
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
            }
            prof_check = sess.get(
                f"{SUPABASE_URL}/rest/v1/profiles?email=eq.{encoded_email}&select=id,email",
                headers=srk_headers,
                timeout=10,
            )
            if prof_check.status_code == 200 and prof_check.json():
                raise HTTPException(
                    status_code=400,
                    detail="An account with this email already exists. Please sign in or use Forgot Password.",
                )

            create_res = sess.post(
                f"{SUPABASE_URL}/auth/v1/admin/users",
                headers=srk_headers,
                json={
                    "email": clean_email,
                    "password": req.password,
                    "email_confirm": True,
                    "user_metadata": {"full_name": clean_name},
                },
                timeout=10,
            )
            if create_res.status_code not in (200, 201):
                err_lower = create_res.text.lower()
                if "already" in err_lower or "exists" in err_lower or "registered" in err_lower or create_res.status_code == 422:
                    raise HTTPException(
                        status_code=400,
                        detail="An account with this email already exists. Please sign in or use Forgot Password.",
                    )
                raise HTTPException(
                    status_code=400,
                    detail=f"Could not create trial account: {create_res.text[:180]}",
                )

            user_id = create_res.json().get("id")
            is_owner = clean_email in ("ammar.akbar2002@gmail.com", "ammar.akbar2069@gmail.com")
            pool_tel = get_account_pool_telemetry() if is_owner else {}
            owner_tokens = int(pool_tel.get("cluster_tokens_remaining", 0))
            owner_episodes = int(pool_tel.get("cluster_episodes_remaining", owner_tokens // 40))
            upsert_res = sess.post(
                f"{SUPABASE_URL}/rest/v1/profiles",
                headers={**srk_headers, "Prefer": "resolution=merge-duplicates,return=representation"},
                json={
                    "id": user_id,
                    "email": clean_email,
                    "full_name": clean_name,
                    "role": "admin" if is_owner else "user",
                    "plan_tier": "both_daily" if is_owner else "both_starter",
                    "credits_balance": owner_tokens if is_owner else 0,
                    "sandbox_runs_remaining": owner_episodes if is_owner else 3,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                timeout=10,
            )
            if upsert_res.status_code >= 400:
                raise HTTPException(
                    status_code=500,
                    detail=f"Trial profile creation failed: {upsert_res.text[:180]}",
                )
            return {
                "status": "created",
                "user_id": user_id,
                "email": clean_email,
                "full_name": clean_name,
                "role": "admin" if is_owner else "user",
                "plan_tier": "both_daily" if is_owner else "both_starter",
                "credits_balance": owner_tokens if is_owner else 0,
                "sandbox_runs_remaining": owner_episodes if is_owner else 3,
                "message": "Free trial account created! Sign in to test Storyboard Preview and 3 Sandbox renders.",
            }

        # Fallback to public signup endpoint if service role key is absent
        signup_res = sess.post(
            f"{SUPABASE_URL}/auth/v1/signup",
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={
                "email": clean_email,
                "password": req.password,
                "data": {"full_name": clean_name},
            },
            timeout=10,
        )
        if signup_res.status_code >= 400:
            err_lower = signup_res.text.lower()
            if "already" in err_lower or "exists" in err_lower or "registered" in err_lower:
                raise HTTPException(
                    status_code=400,
                    detail="An account with this email already exists. Please sign in or use Forgot Password.",
                )
            raise HTTPException(status_code=400, detail=f"Signup failed: {signup_res.text[:180]}")
        body = signup_res.json()
        user_obj = body.get("user") or body
        return {
            "status": "created",
            "user_id": user_obj.get("id", ""),
            "email": clean_email,
            "full_name": clean_name,
            "role": "user",
            "plan_tier": "both_starter",
            "credits_balance": 0,
            "sandbox_runs_remaining": 3,
            "message": "Free trial account created! Sign in to test Storyboard Preview and 3 Sandbox renders.",
        }

    return await asyncio.to_thread(_signup_sync)


@app.post("/api/director/preview", tags=["AI Director"])
async def api_director_preview(req: DirectorPreviewRequest, request: Request):
    """
    Compiles a user's free-form custom prompt (or manual scenes / prebuilt channel)
    into a structured 4-scene EpisodeScript with camera trajectories, English dialogue,
    and Urdu/Roman Urdu dialogue so the creator can inspect and edit every shot before rendering.
    """
    if req.channel not in NICHE_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid channel: {req.channel}")

    auth = _resolve_caller_authorization(request)
    director = MultiChannelDirector()

    if req.creation_mode == "manual_scenes" and req.custom_scenes:
        episode = director.compile_manual_episode(
            custom_scenes=[s.model_dump() for s in req.custom_scenes],
            title=req.custom_prompt or "Custom Manual 3D Episode",
            visual_style=req.visual_style,
            channel=req.channel,
        )
    elif req.creation_mode == "custom_director":
        if not req.custom_prompt or len(req.custom_prompt.strip()) < 4:
            raise HTTPException(
                status_code=400,
                detail="Please enter a custom prompt or topic (at least 4 characters).",
            )
        if auth["is_authenticated"]:
            # Logged-in Supabase user or Studio Admin Key: invoke live Gemini 2.5 Flash Director
            episode = director.generate_custom_episode(
                custom_prompt=req.custom_prompt,
                visual_style=req.visual_style,
                channel=req.channel,
            )
        else:
            # Anonymous visitor: use deterministic 4-shot camera matrix compiler (zero Gemini quota drain)
            style_dna = director._resolve_style_dna(req.visual_style, req.channel)
            episode = director._fallback_custom_episode(
                clean_prompt=req.custom_prompt.strip(),
                style_dna=style_dna,
                channel=req.channel,
            )
    else:
        if auth["is_authenticated"]:
            episode = director.generate_episode(channel=req.channel)
        else:
            style_dna = director._resolve_style_dna(req.visual_style, req.channel)
            episode = director._fallback_custom_episode(
                clean_prompt=f"{req.channel.replace('_', ' ').title()} signature episode",
                style_dna=style_dna,
                channel=req.channel,
            )

    return {
        "creation_mode": req.creation_mode,
        "channel": episode.channel,
        "concept": episode.concept,
        "title_english": episode.title_english,
        "title_urdu": episode.title_urdu,
        "hook_text_english": episode.hook_text_english,
        "hook_text_urdu": episode.hook_text_urdu,
        "scenes": [s.flow_prompt for s in episode.scenes],
        "dialogue_english": [
            {"speaker": d.speaker, "voice_persona": d.voice_persona, "line": d.line}
            for d in episode.dialogue_english
        ],
        "dialogue_urdu": [
            {"speaker": d.speaker, "voice_persona": d.voice_persona, "line": d.line}
            for d in episode.dialogue_urdu
        ],
        "hashtags": episode.hashtags,
        "compiled_by": "gemini_2.5_director" if auth["is_authenticated"] else "deterministic_camera_compiler",
    }


# ─── Voice Cast Catalog & Live Audio Preview ─────────────────────────────────

CHANNEL_DEFAULT_VOICES: Dict[str, str] = {
    "body_simulator": "Charon",
    "xray_mechanics": "Fenrir",
    "crazy_characters": "Puck",
    "health_coach": "Kore",
    "garage_guru": "Fenrir",
    "code_classroom": "Aoede",
}

CHANNEL_SAMPLE_LINES: Dict[str, Dict[str, str]] = {
    "body_simulator": {
        "english": "Red alert in the bloodstream! Five hundred milligrams of raw caffeine just hit the stomach lining!",
        "urdu": "Arrey Maalik! Raat ke do baje itni teekhi biryani kaun khata hai?! Stomach jal raha hai!",
    },
    "xray_mechanics": {
        "english": "Inside the cylinder head at six thousand RPM, micro-fractures ignite a catastrophic thermal runaway.",
        "urdu": "Radiator mein sadah paani daloge toh head gasket aise hi phatega, andar ka x-ray dekho!",
    },
    "crazy_characters": {
        "english": "Wait a second! When the boiling oil hit the pan, Aalu jumped straight onto the kitchen counter!",
        "urdu": "Oye Tamatar bhai! Kadhai garam ho gayi hai, aaj toh apni crispy fries banne wali hain!",
    },
    "health_coach": {
        "english": "Eating soluble fiber ten minutes before carbohydrates slashes your post-meal glucose spike by forty percent.",
        "urdu": "Khane se pehle sirf ek katori salad aapke blood sugar spike ko chaalis feesad tak kam kar deta hai.",
    },
    "garage_guru": {
        "english": "Lock the rear differential before you hit that mud trench, or your axle bearings are toast.",
        "urdu": "4x4 low-range lagao ustaad, warna iss keechad mein clutch plate dhuan chhor degi!",
    },
    "code_classroom": {
        "english": "You allocated ten megabytes on the heap without a destructor? Congratulations, your server just leaked!",
        "urdu": "Bina pointer samjhe AI se code copy karoge toh production server aise hi crash hoga!",
    },
}

VOICE_PERSONA_SPECS: Dict[str, Dict[str, Any]] = {
    "Charon": {
        "voice_id": "Charon",
        "id": "Charon",
        "name": "Charon — Deep Documentary Baritone",
        "gender": "Male",
        "style": VOICE_CONFIGS["narrator"]["style"],
        "style_urdu": VOICE_CONFIGS["farhan"]["style"],
        "edge_voice_en": VOICE_CONFIGS["narrator"]["edge_voice"],
        "edge_voice_ur": VOICE_CONFIGS["farhan"]["edge_voice"],
        "rate": VOICE_CONFIGS["narrator"]["rate"],
        "pitch": VOICE_CONFIGS["narrator"]["pitch"],
        "characters": [k for k, v in VOICE_CONFIGS.items() if v.get("voice") == "Charon"],
    },
    "Kore": {
        "voice_id": "Kore",
        "id": "Kore",
        "name": "Kore — Warm Empathetic Guide",
        "gender": "Female",
        "style": VOICE_CONFIGS["mehak"]["style"],
        "style_urdu": VOICE_CONFIGS["mehak"]["style"],
        "edge_voice_en": "en-US-AriaNeural",
        "edge_voice_ur": VOICE_CONFIGS["mehak"]["edge_voice"],
        "rate": VOICE_CONFIGS["mehak"]["rate"],
        "pitch": VOICE_CONFIGS["mehak"]["pitch"],
        "characters": [k for k, v in VOICE_CONFIGS.items() if v.get("voice") == "Kore"],
    },
    "Puck": {
        "voice_id": "Puck",
        "id": "Puck",
        "name": "Puck — High-Energy Comedic Spark",
        "gender": "Male",
        "style": VOICE_CONFIGS["stomach"]["style"],
        "style_urdu": VOICE_CONFIGS["aalu"]["style"],
        "edge_voice_en": VOICE_CONFIGS["student"]["edge_voice"],
        "edge_voice_ur": VOICE_CONFIGS["stomach"]["edge_voice"],
        "rate": VOICE_CONFIGS["stomach"]["rate"],
        "pitch": VOICE_CONFIGS["stomach"]["pitch"],
        "characters": [k for k, v in VOICE_CONFIGS.items() if v.get("voice") == "Puck"],
    },
    "Fenrir": {
        "voice_id": "Fenrir",
        "id": "Fenrir",
        "name": "Fenrir — Gritty Master Engineer",
        "gender": "Male",
        "style": VOICE_CONFIGS["mechanic"]["style"],
        "style_urdu": VOICE_CONFIGS["muscle"]["style"],
        "edge_voice_en": VOICE_CONFIGS["mechanic"]["edge_voice"],
        "edge_voice_ur": VOICE_CONFIGS["muscle"]["edge_voice"],
        "rate": VOICE_CONFIGS["mechanic"]["rate"],
        "pitch": VOICE_CONFIGS["mechanic"]["pitch"],
        "characters": [k for k, v in VOICE_CONFIGS.items() if v.get("voice") == "Fenrir"],
    },
    "Aoede": {
        "voice_id": "Aoede",
        "id": "Aoede",
        "name": "Aoede — Crisp Studio Host",
        "gender": "Female",
        "style": VOICE_CONFIGS["melody"]["style"],
        "style_urdu": VOICE_CONFIGS["chai"]["style"],
        "edge_voice_en": VOICE_CONFIGS["melody"]["edge_voice"],
        "edge_voice_ur": VOICE_CONFIGS["chai"]["edge_voice"],
        "rate": VOICE_CONFIGS["melody"]["rate"],
        "pitch": VOICE_CONFIGS["melody"]["pitch"],
        "characters": [k for k, v in VOICE_CONFIGS.items() if v.get("voice") == "Aoede"],
    },
}

_vox_preview_engine: Optional[VoxStudioEngine] = None


def _get_vox_preview_engine() -> VoxStudioEngine:
    global _vox_preview_engine
    if _vox_preview_engine is None:
        _vox_preview_engine = VoxStudioEngine()
    return _vox_preview_engine


def _write_fallback_tone_wav(output_wav: Path, duration_sec: float = 1.6) -> None:
    """Writes a clean 24kHz 16-bit mono chime WAV if both cloud TTS tiers are unreachable."""
    sample_rate = 24000
    n_samples = int(sample_rate * duration_sec)
    frames = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        env = min(1.0, i / 1200.0) * math.exp(-2.2 * t)
        val = int(12000 * env * (0.65 * math.sin(2.0 * math.pi * 440.0 * t) + 0.35 * math.sin(2.0 * math.pi * 659.25 * t)))
        frames.extend(struct.pack("<h", max(-32767, min(32767, val))))
    with wave.open(str(output_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(frames))


@app.get("/api/voices/catalog", tags=["Voices"])
async def get_voices_catalog():
    """
    Returns the 5 Gemini/Edge studio voice personas (Charon, Kore, Puck, Fenrir, Aoede)
    with their acting style descriptions from VOICE_CONFIGS, channel-to-default-voice
    mappings, and default sample audition lines in English and Urdu for each channel.
    """
    voices_list = []
    for vid, spec in VOICE_PERSONA_SPECS.items():
        default_for = [ch for ch, def_v in CHANNEL_DEFAULT_VOICES.items() if def_v == vid]
        voices_list.append({
            **spec,
            "default_channels": default_for,
        })
    return {
        "voices": voices_list,
        "channel_defaults": CHANNEL_DEFAULT_VOICES,
        "sample_lines": CHANNEL_SAMPLE_LINES,
        "character_configs": VOICE_CONFIGS,
    }


@app.post("/api/voices/preview", tags=["Voices"])
async def api_voice_preview(req: VoicePreviewRequest):
    """
    Synthesizes a short voice preview .wav file using VoxStudioEngine into
    output/voice_previews/preview_{hash}.wav, returning the cached file immediately
    if it already exists on disk so repeat plays are instant.
    """
    raw_vid = (req.voice_id or "").strip()
    canonical_voice = None
    for k in VOICE_PERSONA_SPECS:
        if k.lower() == raw_vid.lower():
            canonical_voice = k
            break
    if not canonical_voice and raw_vid.lower() in VOICE_CONFIGS:
        canonical_voice = VOICE_CONFIGS[raw_vid.lower()].get("voice", "Charon")
    if not canonical_voice:
        canonical_voice = CHANNEL_DEFAULT_VOICES.get(req.channel, "Charon")

    persona_spec = VOICE_PERSONA_SPECS[canonical_voice]
    channel_key = req.channel if req.channel in CHANNEL_SAMPLE_LINES else "body_simulator"
    lang_key = "urdu" if req.lang == "urdu" else "english"

    sample_text = (req.text or "").strip()
    if not sample_text:
        sample_text = CHANNEL_SAMPLE_LINES[channel_key][lang_key]

    style_desc = persona_spec["style_urdu"] if lang_key == "urdu" else persona_spec["style"]
    edge_voice = persona_spec["edge_voice_ur"] if lang_key == "urdu" else persona_spec["edge_voice_en"]

    digest = hashlib.md5(
        f"{canonical_voice}|{lang_key}|{sample_text}".encode("utf-8")
    ).hexdigest()[:16]
    filename = f"preview_{digest}.wav"
    preview_dir = OUTPUT_DIR / "voice_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    target_wav = preview_dir / filename

    if target_wav.exists() and target_wav.stat().st_size > 200:
        return {
            "status": "ok",
            "voice_id": canonical_voice,
            "channel": channel_key,
            "lang": lang_key,
            "cached": True,
            "audio_url": f"/api/voices/sample/{filename}",
            "style": style_desc,
        }

    synth_spec = {
        "voice": canonical_voice,
        "edge_voice": edge_voice,
        "rate": persona_spec["rate"],
        "pitch": persona_spec["pitch"],
        "style": style_desc,
    }

    vox = _get_vox_preview_engine()
    try:
        await asyncio.to_thread(vox._synthesize_turn_gemini, synth_spec, sample_text, target_wav)
    except Exception:
        try:
            await vox._synthesize_turn_edge(
                synth_spec,
                sample_text,
                target_wav,
                character_key=canonical_voice.lower(),
            )
        except Exception:
            await asyncio.to_thread(_write_fallback_tone_wav, target_wav)

    return {
        "status": "ok",
        "voice_id": canonical_voice,
        "channel": channel_key,
        "lang": lang_key,
        "cached": False,
        "audio_url": f"/api/voices/sample/{filename}",
        "style": style_desc,
    }


@app.get("/api/voices/sample/{filename}", tags=["Voices"])
async def stream_voice_sample(filename: str):
    """Streams output/voice_previews/{filename} safely with path-traversal protection."""
    if "/" in filename or "\\" in filename or ".." in filename or not filename.endswith(".wav"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    preview_dir = (OUTPUT_DIR / "voice_previews").resolve()
    target = (preview_dir / filename).resolve()
    if not str(target).startswith(str(preview_dir)) or not target.exists():
        raise HTTPException(status_code=404, detail="Voice preview audio not found")

    return FileResponse(str(target), media_type="audio/wav")


@app.get("/api/pricing", tags=["SaaS"])
async def get_pricing_calculator(
    language_tier: str = Query("both", pattern="^(urdu|english|both)$"),
    monthly_views: int = Query(500_000, ge=10_000, le=50_000_000),
):
    return calculate_pricing_comparison(language_tier=language_tier, monthly_views=monthly_views)


@app.get("/api/vault", tags=["SaaS"])
async def get_rendered_vault(request: Request):
    """
    Multi-tenant Episode Vault:
      - Unauthenticated public visitors (on the marketing landing page) see the showcase demo episodes.
      - Founder Admin sees the complete master studio vault across all accounts.
      - Logged-in Client accounts strictly see ONLY the episodes generated by their own account (`user_id`).
    """
    auth = _resolve_caller_authorization(request)
    sb_user = auth.get("user")
    is_admin = bool(auth["mode"] == "studio_key" or (sb_user and sb_user.get("role") == "admin"))

    if sb_user and not is_admin:
        # Strict multi-tenant client isolation: collect only video URLs produced by this client's jobs
        user_id = sb_user["id"]
        allowed_urls = set()

        for j in list_job_records(limit=200, user_id=user_id, is_admin=False):
            if j.get("english_video"):
                allowed_urls.add(j["english_video"])
            if j.get("urdu_video"):
                allowed_urls.add(j["urdu_video"])

        if SUPABASE_URL and SUPABASE_ANON_KEY and sb_user.get("jwt"):
            try:
                enc_uid = urllib.parse.quote(str(user_id), safe="")
                sb_jobs = await asyncio.to_thread(
                    lambda: _get_http_session().get(
                        f"{SUPABASE_URL}/rest/v1/render_jobs?user_id=eq.{enc_uid}&select=english_video,urdu_video",
                        headers={
                            "apikey": SUPABASE_ANON_KEY,
                            "Authorization": f"Bearer {sb_user['jwt']}",
                        },
                        timeout=6,
                    )
                )
                if sb_jobs.status_code == 200:
                    for row in sb_jobs.json():
                        if row.get("english_video"):
                            allowed_urls.add(row["english_video"])
                        if row.get("urdu_video"):
                            allowed_urls.add(row["urdu_video"])
            except Exception:
                pass

        pairs = discover_rendered_vault(allowed_video_urls=allowed_urls)
        return {"count": len(pairs), "scope": "client_private", "episodes": pairs}

    # For Founder Admin on Vercel, merge static manifest with any newly completed Supabase render_jobs
    if is_admin and os.environ.get("VERCEL") and SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        try:
            admin_urls = set()
            base_pairs = discover_rendered_vault(allowed_video_urls=None)
            for bp in base_pairs:
                if bp.get("english", {}).get("video_url"):
                    admin_urls.add(bp["english"]["video_url"])
                if bp.get("urdu", {}).get("video_url"):
                    admin_urls.add(bp["urdu"]["video_url"])
            sb_all = await asyncio.to_thread(
                lambda: _get_http_session().get(
                    f"{SUPABASE_URL}/rest/v1/render_jobs?status=eq.completed&select=english_video,urdu_video&limit=100",
                    headers={
                        "apikey": SUPABASE_SERVICE_ROLE_KEY,
                        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    },
                    timeout=6,
                )
            )
            if sb_all.status_code == 200:
                for row in sb_all.json():
                    if row.get("english_video"):
                        admin_urls.add(row["english_video"])
                    if row.get("urdu_video"):
                        admin_urls.add(row["urdu_video"])
            pairs = discover_rendered_vault(allowed_video_urls=admin_urls)
            return {"count": len(pairs), "scope": "founder_master", "episodes": pairs}
        except Exception:
            pass

    pairs = discover_rendered_vault(allowed_video_urls=None)
    return {
        "count": len(pairs),
        "scope": "founder_master" if is_admin else "public_showcase",
        "episodes": pairs,
    }


@app.get("/api/pool-status", tags=["SaaS"])
async def get_pool_status(request: Request):
    _require_founder_admin(request)
    return get_account_pool_telemetry()


@app.post("/api/pool/set-tokens", tags=["SaaS"])
async def api_set_pool_tokens(req: PoolTokenAdjustmentRequest, request: Request):
    """Allows Founder Admin to update or calibrate account Flow generation tokens."""
    _require_founder_admin(request)
    from video_engine.pool_manager import FlowPoolManager
    pm = FlowPoolManager()
    target_acc = req.account_name
    if target_acc.startswith("node_"):
        try:
            n_idx = int(target_acc.split("_")[1]) - 1
            if 0 <= n_idx < len(config.ACTIVE_ACCOUNTS):
                target_acc = config.ACTIVE_ACCOUNTS[n_idx]
        except Exception:
            pass

    pm.set_account_tokens(target_acc, req.tokens_remaining, req.tokens_total or 1000)
    return {"status": "ok", "account": target_acc, "telemetry": get_account_pool_telemetry()}


@app.get("/api/series", tags=["SaaS"])
async def api_list_series(request: Request):
    auth = _resolve_caller_authorization(request)
    sb_user = auth.get("user")
    is_admin = bool(auth["mode"] == "studio_key" or (sb_user and sb_user.get("role") == "admin"))

    # Query Supabase public.series when user is authenticated via Supabase
    if sb_user and SUPABASE_URL and SUPABASE_ANON_KEY:
        try:
            hdrs = (
                {"apikey": SUPABASE_SERVICE_ROLE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"}
                if (is_admin and SUPABASE_SERVICE_ROLE_KEY)
                else {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {sb_user['jwt']}"}
            )
            enc_uid = urllib.parse.quote(str(sb_user["id"]), safe="")
            q_url = f"{SUPABASE_URL}/rest/v1/series?order=created_at.desc&limit=25"
            if not is_admin:
                q_url += f"&user_id=eq.{enc_uid}"
            sb_res = await asyncio.to_thread(lambda: _get_http_session().get(q_url, headers=hdrs, timeout=6))
            if sb_res.status_code == 200:
                rows = sb_res.json()
                for item in rows:
                    plan = PRICING_PLANS.get(item.get("plan_id", ""), {})
                    item["price_usd"] = plan.get("price_usd", 0)
                if rows or os.environ.get("VERCEL"):
                    return {"series": rows}
        except Exception:
            pass

    if is_admin:
        return {"series": list_series_records(is_admin=True)}
    if sb_user:
        return {"series": list_series_records(user_id=sb_user["id"], is_admin=False)}
    return {"series": []}


@app.post("/api/series", tags=["SaaS"])
async def api_create_series(req: SeriesCreateRequest, request: Request):
    auth = _resolve_caller_authorization(request)
    if not auth["is_authenticated"]:
        raise HTTPException(
            status_code=401,
            detail="Please sign in with your account before saving a recurring series.",
        )
    sb_user = auth.get("user")
    uid = sb_user["id"] if sb_user else "admin"
    uemail = sb_user["email"] if sb_user else ""
    try:
        record = create_series_record(
            name=req.name,
            channel=req.channel,
            language_tier=req.language_tier,
            plan_id=req.plan_id,
            creation_mode=req.creation_mode,
            custom_prompt=req.custom_prompt,
            visual_style_dna=req.visual_style,
            user_id=uid,
            user_email=uemail,
        )
        if sb_user and SUPABASE_URL and SUPABASE_ANON_KEY:
            try:
                sb_post = await asyncio.to_thread(
                    lambda: _get_http_session().post(
                        f"{SUPABASE_URL}/rest/v1/series",
                        headers={
                            "apikey": SUPABASE_ANON_KEY,
                            "Authorization": f"Bearer {sb_user['jwt']}",
                            "Content-Type": "application/json",
                            "Prefer": "return=representation",
                        },
                        json={
                            "user_id": sb_user["id"],
                            "name": record["name"],
                            "creation_mode": record["creation_mode"],
                            "channel": record["channel"],
                            "language_tier": record["language_tier"],
                            "custom_prompt": record["custom_prompt"],
                            "visual_style_dna": record["visual_style_dna"],
                            "plan_id": record["plan_id"],
                            "cadence": record["cadence"],
                            "status": "active",
                        },
                        timeout=6,
                    )
                )
                if sb_post.status_code in (200, 201) and sb_post.json():
                    record["supabase_id"] = sb_post.json()[0].get("id")
            except Exception:
                pass
        return record
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/api/series/{series_id}", tags=["SaaS"])
async def api_update_series_status(
    series_id: str,
    request: Request,
    req: Optional[SeriesStatusUpdateRequest] = None,
):
    """
    Toggles or sets a recurring series status between 'active' and 'paused'
    in both SQLite and Supabase public.series (scoped to the user or admin).
    """
    auth = _resolve_caller_authorization(request)
    if not auth["is_authenticated"]:
        raise HTTPException(status_code=401, detail="Sign in required to update a saved series.")

    sb_user = auth.get("user")
    is_admin = bool(auth["mode"] == "studio_key" or (sb_user and sb_user.get("role") == "admin"))
    uid = sb_user["id"] if sb_user else "admin"
    requested_status = req.status if (req and req.status in ("active", "paused")) else None

    local_updated = update_series_status_record(
        series_id=series_id,
        status=requested_status,
        user_id=uid,
        is_admin=is_admin,
    )
    resolved_status = local_updated["status"] if local_updated else (requested_status or "paused")
    sb_updated_row = None

    if SUPABASE_URL and (SUPABASE_SERVICE_ROLE_KEY or (sb_user and SUPABASE_ANON_KEY)):
        try:
            hdrs = (
                {
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                }
                if SUPABASE_SERVICE_ROLE_KEY
                else {
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {sb_user['jwt']}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                }
            )
            enc_sid = urllib.parse.quote(str(series_id).strip(), safe="")
            q_filter = f"id=eq.{enc_sid}"
            if sb_user and not is_admin:
                enc_uid = urllib.parse.quote(str(sb_user["id"]), safe="")
                q_filter += f"&user_id=eq.{enc_uid}"

            if not requested_status and not local_updated:
                cur_res = await asyncio.to_thread(
                    lambda: _get_http_session().get(
                        f"{SUPABASE_URL}/rest/v1/series?{q_filter}&select=id,status",
                        headers=hdrs,
                        timeout=6,
                    )
                )
                if cur_res.status_code == 200 and cur_res.json():
                    cur_st = cur_res.json()[0].get("status", "active")
                    resolved_status = "paused" if cur_st == "active" else "active"

            patch_res = await asyncio.to_thread(
                lambda: _get_http_session().patch(
                    f"{SUPABASE_URL}/rest/v1/series?{q_filter}",
                    headers=hdrs,
                    json={"status": resolved_status},
                    timeout=6,
                )
            )
            if patch_res.status_code == 200 and patch_res.json():
                sb_updated_row = patch_res.json()[0]
        except Exception:
            pass

    if not local_updated and not sb_updated_row:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    return {
        "status": resolved_status,
        "series_id": series_id,
        "series": sb_updated_row or local_updated,
    }


@app.delete("/api/series/{series_id}", tags=["SaaS"])
async def api_delete_series(series_id: str, request: Request):
    """
    Deletes a saved recurring series from both SQLite and Supabase public.series
    (scoped to the authenticated owner or admin).
    """
    auth = _resolve_caller_authorization(request)
    if not auth["is_authenticated"]:
        raise HTTPException(status_code=401, detail="Sign in required to delete a saved series.")

    sb_user = auth.get("user")
    is_admin = bool(auth["mode"] == "studio_key" or (sb_user and sb_user.get("role") == "admin"))
    uid = sb_user["id"] if sb_user else "admin"

    deleted_local = delete_series_record(series_id=series_id, user_id=uid, is_admin=is_admin)
    deleted_sb = False

    if SUPABASE_URL and (SUPABASE_SERVICE_ROLE_KEY or (sb_user and SUPABASE_ANON_KEY)):
        try:
            hdrs = (
                {
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Prefer": "return=representation",
                }
                if SUPABASE_SERVICE_ROLE_KEY
                else {
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {sb_user['jwt']}",
                    "Prefer": "return=representation",
                }
            )
            enc_sid = urllib.parse.quote(str(series_id).strip(), safe="")
            q_filter = f"id=eq.{enc_sid}"
            if sb_user and not is_admin:
                enc_uid = urllib.parse.quote(str(sb_user["id"]), safe="")
                q_filter += f"&user_id=eq.{enc_uid}"

            del_res = await asyncio.to_thread(
                lambda: _get_http_session().delete(
                    f"{SUPABASE_URL}/rest/v1/series?{q_filter}",
                    headers=hdrs,
                    timeout=6,
                )
            )
            if del_res.status_code in (200, 204):
                deleted_sb = True
        except Exception:
            pass

    if not deleted_local and not deleted_sb:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    return {"status": "deleted", "series_id": series_id}


@app.get("/api/jobs", tags=["SaaS"])
async def api_list_jobs(request: Request):
    auth = _resolve_caller_authorization(request)
    sb_user = auth.get("user")
    is_admin = bool(auth["mode"] == "studio_key" or (sb_user and sb_user.get("role") == "admin"))

    # Query live Supabase public.render_jobs so Vercel & local UI always reflect real-time worker progress
    if sb_user and SUPABASE_URL and SUPABASE_ANON_KEY:
        try:
            hdrs = (
                {"apikey": SUPABASE_SERVICE_ROLE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"}
                if (is_admin and SUPABASE_SERVICE_ROLE_KEY)
                else {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {sb_user['jwt']}"}
            )
            enc_uid = urllib.parse.quote(str(sb_user["id"]), safe="")
            q_url = f"{SUPABASE_URL}/rest/v1/render_jobs?order=created_at.desc&limit=25"
            if not is_admin:
                q_url += f"&user_id=eq.{enc_uid}"
            sb_res = await asyncio.to_thread(lambda: _get_http_session().get(q_url, headers=hdrs, timeout=6))
            if sb_res.status_code == 200:
                sb_rows = sb_res.json()
                normalized = []
                for r in sb_rows:
                    normalized.append({
                        "job_id": r.get("job_code") or r.get("id", "")[:12],
                        "user_id": r.get("user_id", ""),
                        "channel": r.get("channel", "body_simulator"),
                        "lang": r.get("lang", "both"),
                        "creation_mode": r.get("creation_mode", "prebuilt"),
                        "mock_mode": 1 if r.get("mock_mode") else 0,
                        "status": r.get("status", "queued"),
                        "stage": r.get("stage", ""),
                        "progress": r.get("progress", 10),
                        "concept": r.get("concept", ""),
                        "english_video": r.get("english_video", ""),
                        "urdu_video": r.get("urdu_video", ""),
                        "error": r.get("error", ""),
                    })
                if normalized or os.environ.get("VERCEL"):
                    return {"jobs": normalized}
        except Exception:
            pass

    if is_admin:
        return {"jobs": list_job_records(limit=25, is_admin=True)}
    if sb_user:
        return {"jobs": list_job_records(limit=25, user_id=sb_user["id"], is_admin=False)}
    return {"jobs": list_job_records(limit=25, user_id="anonymous", is_admin=False)}


@app.post("/api/jobs/{job_id}/cancel", tags=["SaaS"])
async def api_cancel_job(job_id: str, request: Request):
    """
    Cancels a queued or running render job in both local execution and Supabase public.render_jobs.
    """
    auth = _resolve_caller_authorization(request)
    if not auth["is_authenticated"]:
        raise HTTPException(status_code=401, detail="Sign in required to cancel a render job.")

    _cancelled_jobs.add(job_id)

    # Cancel active local ProactorEventLoop task if running in this process
    active_pair = _active_job_threads.get(job_id)
    if active_pair:
        loop_obj, task_obj = active_pair
        try:
            loop_obj.call_soon_threadsafe(task_obj.cancel)
        except Exception:
            pass

    update_job_record(
        job_id,
        status="cancelled",
        stage="Cancelled by user",
        error="",
    )

    sb_user = auth.get("user")
    is_admin = bool(auth["mode"] == "studio_key" or (sb_user and sb_user.get("role") == "admin"))
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        enc_code = urllib.parse.quote(str(job_id), safe="")
        q = f"{SUPABASE_URL}/rest/v1/render_jobs?job_code=eq.{enc_code}"
        if sb_user and not is_admin:
            enc_uid = urllib.parse.quote(str(sb_user["id"]), safe="")
            q += f"&user_id=eq.{enc_uid}"
        await asyncio.to_thread(
            lambda: _get_http_session().patch(
                q,
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "status": "cancelled",
                    "stage": "Cancelled by user",
                    "error": "",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                timeout=8,
            )
        )

    return {"status": "cancelled", "job_id": job_id}


@app.post("/api/generate", tags=["SaaS"])
async def api_trigger_generate(
    req: GenerateEpisodeRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    if req.channel not in NICHE_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid channel: {req.channel}")

    auth = _resolve_caller_authorization(request)

    # SECURITY GATE: Live Google Flow / Playwright renders (mock=False) strictly require
    # STUDIO_ADMIN_KEY OR an authenticated Supabase account with admin role or live credits > 0.
    if not req.mock and not auth["can_live_render"]:
        raise HTTPException(
            status_code=401,
            detail="Valid customer login with active render credits (or Admin access) is required to dispatch renders.",
        )

    # Multi-language support (english, urdu, both) is included standard across all plans
    sb_user = auth.get("user")
    serialized_scenes = [s.model_dump() for s in req.custom_scenes] if req.custom_scenes else []
    uid = sb_user["id"] if sb_user else ("admin" if auth["can_live_render"] else "anonymous")
    uemail = sb_user["email"] if sb_user else ""

    job = create_job_record(
        channel=req.channel,
        lang=req.lang,
        mock_mode=req.mock,
        series_id=req.series_id,
        creation_mode=req.creation_mode,
        custom_prompt=req.custom_prompt,
        visual_style_dna=req.visual_style,
        custom_scenes=serialized_scenes,
        user_id=uid,
        user_email=uemail,
    )

    # Coordinate single execution between cloud/worker queue vs local direct execution:
    # - On Vercel, jobs are queued in Supabase (`status = 'queued'`) and claimed by `supabase_worker.py`.
    # - Locally, if `api_server.py` executes the job directly, it inserts the Supabase record as
    #   `status = 'running'` so `supabase_worker.py` never claims or double-renders the same job.
    is_vercel = bool(os.environ.get("VERCEL"))
    will_run_locally = bool(auth["can_live_render"] and not is_vercel)
    initial_sb_status = "running" if will_run_locally else "queued"
    initial_sb_stage = (
        "[1/6] Claimed by Local Studio Server — Initializing AI Director..."
        if will_run_locally
        else "[0/6] Queued in Flow Worker Pool"
    )

    sb_user = auth.get("user")
    if sb_user and SUPABASE_URL and SUPABASE_ANON_KEY:
        try:
            sb_resp = await asyncio.to_thread(
                lambda: _get_http_session().post(
                    f"{SUPABASE_URL}/rest/v1/render_jobs",
                    headers={
                        "apikey": SUPABASE_ANON_KEY,
                        "Authorization": f"Bearer {sb_user['jwt']}",
                        "Content-Type": "application/json",
                        "Prefer": "return=representation",
                    },
                    json={
                        "job_code": job["job_id"],
                        "user_id": sb_user["id"],
                        "creation_mode": req.creation_mode,
                        "channel": req.channel,
                        "lang": req.lang,
                        "custom_prompt": req.custom_prompt,
                        "visual_style_dna": req.visual_style,
                        "custom_scenes": serialized_scenes,
                        "mock_mode": req.mock,
                        "status": initial_sb_status,
                        "stage": initial_sb_stage,
                        "progress": 15 if will_run_locally else 5,
                        "concept": (req.custom_prompt or req.channel)[:160],
                    },
                    timeout=8,
                )
            )
            if sb_resp.status_code >= 400:
                raise HTTPException(
                    status_code=402,
                    detail=f"Supabase Credit Gate: {sb_resp.text[:200]}",
                )
        except HTTPException:
            raise
        except Exception as exc:
            if is_vercel:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to enqueue job in Supabase worker queue: {str(exc)[:160]}",
                )

    if is_vercel and sb_user:
        return job

    if auth["can_live_render"]:
        is_owner = bool(auth["mode"] == "studio_key" or (sb_user and sb_user.get("role") == "admin"))
        user_wa_tok = (
            sb_user.get("wa_agent_token", "")
            if (sb_user and sb_user.get("wa_verified"))
            else ""
        )
        user_wa_uid = (
            sb_user.get("wa_user_id", "")
            if (sb_user and sb_user.get("wa_verified"))
            else ""
        )
        background_tasks.add_task(
            _execute_episode_job,
            job["job_id"],
            req.channel,
            req.lang,
            req.mock,
            req.scenes,
            req.creation_mode,
            req.custom_prompt,
            req.visual_style,
            serialized_scenes,
            user_wa_tok,
            user_wa_uid,
            is_owner,
        )
    else:
        background_tasks.add_task(
            _execute_sandbox_demo_job,
            job["job_id"],
            req.channel,
            req.lang,
            req.creation_mode,
            req.custom_prompt,
            req.visual_style,
        )

    return job


# ─── Per-User WhatsApp Setup & Verification Handshake ───────────────────────

@app.post("/api/whatsapp/test", tags=["WhatsApp"])
async def api_whatsapp_test(req: WhatsAppTestRequest, request: Request):
    """
    Dispatches a live verification message to the logged-in user's WhatsApp number/ID
    using the key they pasted, and saves the credentials in pending state (`wa_verified = false`)
    until the user clicks 'Yes, I received the message'.
    """
    auth = _resolve_caller_authorization(request)
    sb_user = auth.get("user")
    if not sb_user:
        raise HTTPException(status_code=401, detail="Please sign in with your account to configure WhatsApp notifications.")

    from notifications import send_whatsapp_verification_ping

    ping_res = await asyncio.to_thread(
        send_whatsapp_verification_ping,
        req.wa_agent_token,
        req.wa_user_id,
        sb_user.get("email", ""),
    )

    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        enc_uid = urllib.parse.quote(str(sb_user["id"]), safe="")
        await asyncio.to_thread(
            lambda: _get_http_session().patch(
                f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{enc_uid}",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "wa_agent_token": req.wa_agent_token.strip(),
                    "wa_user_id": req.wa_user_id.strip(),
                    "wa_verified": False,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                timeout=8,
            )
        )
        _jwt_profile_cache.clear()

    if not ping_res["ok"]:
        raise HTTPException(status_code=400, detail=ping_res["detail"])

    return {
        "status": "test_sent",
        "message": "Test message dispatched to your WhatsApp. Did you receive the message on your phone?",
    }


@app.post("/api/whatsapp/confirm", tags=["WhatsApp"])
async def api_whatsapp_confirm(req: WhatsAppConfirmRequest, request: Request):
    """
    Finalizes or resets the user's WhatsApp verification status based on whether
    they confirmed receiving the test message on their phone.
    """
    auth = _resolve_caller_authorization(request)
    sb_user = auth.get("user")
    if not sb_user:
        raise HTTPException(status_code=401, detail="Please sign in to confirm your WhatsApp settings.")

    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        enc_uid = urllib.parse.quote(str(sb_user["id"]), safe="")
        resp = await asyncio.to_thread(
            lambda: _get_http_session().patch(
                f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{enc_uid}",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
                json={
                    "wa_verified": bool(req.received),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                timeout=8,
            )
        )
        _jwt_profile_cache.clear()
        if resp.status_code >= 400:
            raise HTTPException(status_code=500, detail=f"Could not save verification state: {resp.text[:160]}")

    return {
        "status": "verified" if req.received else "unverified",
        "wa_verified": bool(req.received),
        "message": (
            "WhatsApp notifications confirmed and active! Future completed videos will be sent directly to your WhatsApp."
            if req.received
            else "Verification reset. Please double-check your Agent Token and User ID and send another test message."
        ),
    }


# ─── Hybrid Lead Capture & Concierge Checkout (Option C) ────────────────────

@app.post("/api/checkout/lead", tags=["Checkout"])
async def api_create_checkout_lead(req: CheckoutLeadRequest):
    """
    Public endpoint: validates and saves a checkout lead in SQLite (and attempts
    optional insert into Supabase public.checkout_leads if present), returning the
    created lead and studio concierge contact details.
    """
    clean_email = req.email.strip().lower()
    if "@" not in clean_email or "." not in clean_email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    normalized_tier = normalize_plan_tier(req.plan_tier)
    if normalized_tier not in PRICING_PLANS:
        raise HTTPException(status_code=400, detail=f"Unknown plan_tier: {req.plan_tier}")

    lead = create_checkout_lead(
        email=clean_email,
        whatsapp=req.whatsapp,
        plan_tier=normalized_tier,
        payment_method=req.payment_method,
        notes=req.notes,
        status="pending",
    )

    if SUPABASE_URL and (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY):
        try:
            key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
            await asyncio.to_thread(
                lambda: _get_http_session().post(
                    f"{SUPABASE_URL}/rest/v1/checkout_leads",
                    headers={
                        "apikey": key,
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "id": lead["id"],
                        "email": lead["email"],
                        "whatsapp": lead["whatsapp"],
                        "plan_tier": lead["plan_tier"],
                        "payment_method": lead["payment_method"],
                        "notes": lead["notes"],
                        "status": lead["status"],
                        "created_at": lead["created_at"],
                    },
                    timeout=6,
                )
            )
        except Exception:
            pass

    return {
        "status": "ok",
        "lead": lead,
        "concierge": {
            "whatsapp": "+923161402546",
            "email": "ammar.akbar2002@gmail.com",
            "message": "Checkout request logged! Complete payment with our studio concierge to activate live 3D render credits.",
        },
    }


@app.get("/api/admin/leads", tags=["Admin"])
async def api_list_checkout_leads(request: Request):
    """Lists all captured checkout leads (Founder Admin only)."""
    _require_founder_admin(request)
    local_leads = list_checkout_leads(limit=100)
    leads_by_id = {item["id"]: item for item in local_leads}

    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        try:
            sb_res = await asyncio.to_thread(
                lambda: _get_http_session().get(
                    f"{SUPABASE_URL}/rest/v1/checkout_leads?select=*&order=created_at.desc&limit=100",
                    headers={
                        "apikey": SUPABASE_SERVICE_ROLE_KEY,
                        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    },
                    timeout=8,
                )
            )
            if sb_res.status_code == 200:
                for row in sb_res.json():
                    lid = str(row.get("id", ""))
                    if lid and lid not in leads_by_id:
                        plan = PRICING_PLANS.get(row.get("plan_tier", ""), {})
                        row["plan_name"] = plan.get("name", row.get("plan_tier", ""))
                        row["price_usd"] = plan.get("price_usd", 0)
                        leads_by_id[lid] = row
        except Exception:
            pass

    merged = sorted(
        leads_by_id.values(),
        key=lambda x: str(x.get("created_at", "")),
        reverse=True,
    )
    return {"leads": merged}


@app.delete("/api/admin/leads/{lead_id}", tags=["Admin"])
async def api_delete_checkout_lead(lead_id: str, request: Request):
    """Deletes/dismisses a checkout lead (Founder Admin only)."""
    _require_founder_admin(request)
    deleted_local = delete_checkout_lead(lead_id)
    deleted_sb = False

    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        try:
            enc_id = urllib.parse.quote(str(lead_id).strip(), safe="")
            sb_del = await asyncio.to_thread(
                lambda: _get_http_session().delete(
                    f"{SUPABASE_URL}/rest/v1/checkout_leads?id=eq.{enc_id}",
                    headers={
                        "apikey": SUPABASE_SERVICE_ROLE_KEY,
                        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    },
                    timeout=8,
                )
            )
            if sb_del.status_code in (200, 204):
                deleted_sb = True
        except Exception:
            pass

    if not deleted_local and not deleted_sb:
        raise HTTPException(status_code=404, detail=f"Lead '{lead_id}' not found.")

    return {"status": "deleted", "lead_id": lead_id}


# ─── Admin Customer Provisioning (Ammar / Founder Only) ─────────────────────

def _require_founder_admin(request: Request) -> Dict[str, Any]:
    auth = _resolve_caller_authorization(request)
    is_admin_user = bool(auth.get("user") and auth["user"].get("role") == "admin")
    if not (_is_authorized_studio_key(request) or is_admin_user):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only the Founder Admin can provision or manage customer accounts.",
        )
    return auth


@app.get("/api/admin/customers", tags=["Admin"])
async def api_list_customers(request: Request):
    """Lists all provisioned accounts in Supabase public.profiles (Founder Admin only)."""
    _require_founder_admin(request)
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=500, detail="Supabase service role key not configured")

    def _fetch_sync():
        return _get_http_session().get(
            f"{SUPABASE_URL}/rest/v1/profiles?select=*&order=created_at.desc",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            },
            timeout=10,
        )

    resp = await asyncio.to_thread(_fetch_sync)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Supabase query error: {resp.text[:200]}")
    customers = resp.json()
    pool_tel = get_account_pool_telemetry()
    live_admin_tokens = int(pool_tel.get("cluster_tokens_remaining", 0))
    live_admin_episodes = int(pool_tel.get("cluster_episodes_remaining", live_admin_tokens // 40))
    for c in customers:
        if c.get("role") == "admin":
            c["credits_balance"] = live_admin_tokens
            c["sandbox_runs_remaining"] = live_admin_episodes
    return {"customers": customers}


@app.delete("/api/admin/customers/{user_id}", tags=["Admin"])
async def api_delete_customer(user_id: str, request: Request):
    """Deletes a customer account from Supabase Auth & cascades public.profiles (Founder Admin only)."""
    _require_founder_admin(request)
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=500, detail="Supabase service role key not configured")

    enc_uid = urllib.parse.quote(str(user_id).strip(), safe="")

    def _del_sync():
        return _get_http_session().delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{enc_uid}",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            },
            timeout=10,
        )

    resp = await asyncio.to_thread(_del_sync)
    if resp.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"Could not delete user: {resp.text[:180]}")
    return {"status": "deleted", "user_id": user_id}


@app.post("/api/admin/provision-customer", tags=["Admin"])
async def api_provision_customer(req: ProvisionCustomerRequest, request: Request):
    """
    Idempotently creates or updates a paying customer's login email & password in Supabase Auth
    and upserts their purchased plan_tier and credits_balance in public.profiles.
    """
    _require_founder_admin(request)
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=500, detail="Supabase service role key not configured")

    normalized_tier = normalize_plan_tier(req.plan_tier)
    plan = PRICING_PLANS.get(normalized_tier)
    if not plan:
        raise HTTPException(status_code=400, detail=f"Unknown plan_tier: {req.plan_tier}")

    credits_to_grant = (
        req.credits_balance
        if req.credits_balance is not None
        else int(plan.get("episodes_per_month", 30))
    )
    clean_email = req.email.strip().lower()
    if "@" not in clean_email or "." not in clean_email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    clean_name = req.full_name.strip() or clean_email.split("@")[0]

    def _provision_sync() -> Dict[str, Any]:
        sess = _get_http_session()
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
        }
        user_id = None
        encoded_email = urllib.parse.quote(clean_email, safe="")

        # 1. Check public.profiles first
        prof_check = sess.get(
            f"{SUPABASE_URL}/rest/v1/profiles?email=eq.{encoded_email}&select=id,email",
            headers=headers,
            timeout=10,
        )
        if prof_check.status_code == 200 and prof_check.json():
            user_id = prof_check.json()[0]["id"]

        # 2. Create or update Auth user
        if not user_id:
            create_res = sess.post(
                f"{SUPABASE_URL}/auth/v1/admin/users",
                headers=headers,
                json={
                    "email": clean_email,
                    "password": req.password,
                    "email_confirm": True,
                    "user_metadata": {"full_name": clean_name},
                },
                timeout=10,
            )
            if create_res.status_code in (200, 201):
                user_id = create_res.json()["id"]
            else:
                # Fallback if email already exists in auth.users
                users_res = sess.get(
                    f"{SUPABASE_URL}/auth/v1/admin/users?per_page=200",
                    headers=headers,
                    timeout=10,
                )
                if users_res.status_code == 200:
                    for u in users_res.json().get("users", []):
                        if (u.get("email") or "").lower() == clean_email:
                            user_id = u["id"]
                            break
                if not user_id:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Supabase Auth error: {create_res.text[:200]}",
                    )

        # Always ensure password & email_confirm are synced on existing user
        enc_uid = urllib.parse.quote(str(user_id), safe="")
        upd_auth = sess.put(
            f"{SUPABASE_URL}/auth/v1/admin/users/{enc_uid}",
            headers=headers,
            json={
                "password": req.password,
                "email_confirm": True,
                "user_metadata": {"full_name": clean_name},
            },
            timeout=10,
        )
        if upd_auth.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Auth password update failed: {upd_auth.text[:180]}")

        # 3. Upsert public.profiles row with purchased plan_tier & credits_balance
        is_owner = clean_email in ("ammar.akbar2002@gmail.com", "ammar.akbar2069@gmail.com")
        upsert_res = sess.post(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers={**headers, "Prefer": "resolution=merge-duplicates,return=representation"},
            json={
                "id": user_id,
                "email": clean_email,
                "full_name": clean_name,
                "role": "admin" if is_owner else "user",
                "plan_tier": normalized_tier,
                "credits_balance": credits_to_grant,
                "sandbox_runs_remaining": 50,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            timeout=10,
        )
        if upsert_res.status_code >= 400:
            raise HTTPException(status_code=500, detail=f"Profile upsert error: {upsert_res.text[:200]}")

        _jwt_profile_cache.clear()

        return {
            "status": "provisioned",
            "user_id": user_id,
            "email": clean_email,
            "password": req.password,
            "full_name": clean_name,
            "plan_tier": normalized_tier,
            "plan_name": plan["name"],
            "language_tier": plan["language_tier"],
            "credits_balance": credits_to_grant,
        }

    return await asyncio.to_thread(_provision_sync)


# ─── Authenticated Cloud Webhooks ────────────────────────────────────────────

@app.post("/trigger/{niche}", response_model=TriggerResponse, dependencies=[Depends(verify_api_key)], tags=["Webhooks"])
async def trigger_generation(niche: str, background_tasks: BackgroundTasks, mock: bool = False, lang: str = "both"):
    if niche not in NICHE_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid niche. Allowed: {list(NICHE_NAMES.keys())}")

    job = create_job_record(channel=niche, lang=lang, mock_mode=mock)
    background_tasks.add_task(_execute_episode_job, job["job_id"], niche, lang, mock, None)

    return TriggerResponse(
        status="accepted",
        message="Video generation pipeline queued successfully in the background.",
        job_id=job["job_id"],
        niche=niche,
    )


@app.get("/status", dependencies=[Depends(verify_api_key)], tags=["System"])
async def get_system_status():
    return list_job_records(limit=25)


if __name__ == "__main__":
    import uvicorn
    print("🌟 Starting VoxFlow Studio SaaS Server (Supabase RLS + Custom AI Director) on http://localhost:8000 ...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
