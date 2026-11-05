import asyncio
import collections
import json
import os
import secrets
import sys
import time
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
from saas_store import (
    CHANNEL_CATALOG,
    PRICING_PLANS,
    VISUAL_STYLE_CATALOG,
    calculate_pricing_comparison,
    create_job_record,
    create_series_record,
    discover_rendered_vault,
    get_account_pool_telemetry,
    init_db,
    list_job_records,
    list_series_records,
    reconcile_stale_jobs,
     update_job_record,
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
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Studio-Key"],
)

init_db()
reconcile_stale_jobs()

STUDIO_ADMIN_KEY = (
    os.environ.get("STUDIO_ADMIN_KEY")
    or os.environ.get("AGENT_API_KEY")
    or "vf_admin_9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c"
)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ouqjlqqgnboytjvudylv.supabase.co").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_PROJECT_REF = os.environ.get("SUPABASE_PROJECT_REF", "ouqjlqqgnboytjvudylv")

SAAS_WEB_DIR = ROOT_DIR / "saas_web"

# Concurrency lock: at most 1 active real Playwright/TTS pipeline job at a time
_pipeline_semaphore = asyncio.Semaphore(1)

# Persistent HTTP Keep-Alive session to Supabase (avoids 800ms TLS handshakes per call)
_http_session = requests.Session()
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
        user_resp = _http_session.get(
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
        prof_resp = _http_session.get(
            f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}&select=*",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {jwt_token}",
            },
            timeout=6,
        )
        if prof_resp.status_code == 200 and prof_resp.json():
            prof = prof_resp.json()[0]
            res_obj = {
                "id": user_id,
                "email": email,
                "role": prof.get("role", "user"),
                "plan_tier": prof.get("plan_tier", "free"),
                "credits_balance": int(prof.get("credits_balance", 0)),
                "sandbox_runs_remaining": int(prof.get("sandbox_runs_remaining", 5)),
                "wa_agent_token": prof.get("wa_agent_token", ""),
                "wa_user_id": prof.get("wa_user_id", ""),
                "wa_verified": bool(prof.get("wa_verified", False)),
                "jwt": jwt_token,
            }
            _jwt_profile_cache[jwt_token] = (now, res_obj)
            return res_obj
        is_owner = email in ("ammar.akbar2002@gmail.com", "ammar.akbar2069@gmail.com")
        res_obj = {
            "id": user_id,
            "email": email,
            "role": "admin" if is_owner else "user",
            "plan_tier": "both_daily" if is_owner else "free",
            "credits_balance": 9999 if is_owner else 0,
            "sandbox_runs_remaining": 9999 if is_owner else 5,
            "jwt": jwt_token,
        }
        _jwt_profile_cache[jwt_token] = (now, res_obj)
        return res_obj
    except Exception:
        return None


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


class ProvisionCustomerRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120, description="Customer login email")
    password: str = Field(..., min_length=6, max_length=100, description="Password to issue to the customer")
    full_name: str = Field("", max_length=80, description="Customer or channel name")
    plan_tier: str = Field(
        "both_daily",
        pattern="^(urdu_starter|urdu_daily|english_starter|english_daily|both_starter|both_daily)$",
    )
    credits_balance: Optional[int] = Field(None, ge=0, le=10000, description="Override credits (defaults to plan episodes)")


class WhatsAppTestRequest(BaseModel):
    wa_agent_token: str = Field(..., min_length=6, max_length=600, description="User's personal WhatsApp Agent API Token")
    wa_user_id: str = Field(..., min_length=3, max_length=120, description="User's personal WhatsApp User ID or Phone Number")


class WhatsAppConfirmRequest(BaseModel):
    received: bool = Field(..., description="True if the user confirmed receiving the test message on their phone")


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


def _run_pipeline_in_proactor_loop(target, *args, **kwargs):
    """
    Executes the async Playwright + TTS + FFmpeg pipeline in a dedicated worker thread
    backed by an explicit Windows ProactorEventLoop.
    Why: Uvicorn on Windows (especially with --reload) sets WindowsSelectorEventLoopPolicy
    on the main thread, where asyncio.create_subprocess_exec() raises NotImplementedError()
    when Playwright launches its browser driver. Accepts either a coroutine or a coroutine factory.
    """
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        coro = target(*args, **kwargs) if callable(target) else target
        return loop.run_until_complete(coro)
    finally:
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
    if _pipeline_semaphore.locked():
        update_job_record(
            job_id,
            status="queued",
            stage="[0/6] Waiting for active Playwright/TTS job to finish...",
            progress=10,
        )

    async with _pipeline_semaphore:
        try:
            update_job_record(
                job_id,
                status="running",
                stage=f"[1/6] AI Director ({creation_mode}): Compiling 4-scene script & shot directives...",
                progress=20,
            )
            await asyncio.sleep(0.2)

            def _progress_cb(stage: str, progress: int, concept: str = None, script_preview: dict = None):
                fields: Dict[str, Any] = {"status": "running", "stage": stage, "progress": progress}
                if concept:
                    fields["concept"] = concept[:160]
                if script_preview:
                    fields["script_preview"] = json.dumps(script_preview, ensure_ascii=False)
                update_job_record(job_id, **fields)

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
                produce_dual_language_episode(
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
                ),
            )

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
            if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
                try:
                    _http_session.patch(
                        f"{SUPABASE_URL}/rest/v1/render_jobs?job_code=eq.{job_id}",
                        headers={
                            "apikey": SUPABASE_SERVICE_ROLE_KEY,
                            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "status": "completed",
                            "stage": "[6/6] Completed — Synced, Ducked & Exported",
                            "progress": 100,
                            "english_video": cdn_en or en_url,
                            "urdu_video": cdn_ur or ur_url,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        timeout=8,
                    )
                except Exception:
                    pass
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            update_job_record(
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
async def get_saas_catalog():
    return {
        "channels": CHANNEL_CATALOG,
        "visual_styles": VISUAL_STYLE_CATALOG,
        "plans": list(PRICING_PLANS.values()),
        "pool": get_account_pool_telemetry(),
    }


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
                sb_jobs = _http_session.get(
                    f"{SUPABASE_URL}/rest/v1/render_jobs?user_id=eq.{user_id}&select=english_video,urdu_video",
                    headers={
                        "apikey": SUPABASE_ANON_KEY,
                        "Authorization": f"Bearer {sb_user['jwt']}",
                    },
                    timeout=6,
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

    pairs = discover_rendered_vault(allowed_video_urls=None)
    return {
        "count": len(pairs),
        "scope": "founder_master" if is_admin else "public_showcase",
        "episodes": pairs,
    }


@app.get("/api/pool-status", tags=["SaaS"])
async def get_pool_status():
    return get_account_pool_telemetry()


@app.get("/api/series", tags=["SaaS"])
async def api_list_series(request: Request):
    auth = _resolve_caller_authorization(request)
    sb_user = auth.get("user")
    is_admin = bool(auth["mode"] == "studio_key" or (sb_user and sb_user.get("role") == "admin"))
    if is_admin:
        return {"series": list_series_records(is_admin=True)}
    if sb_user:
        return {"series": list_series_records(user_id=sb_user["id"], is_admin=False)}
    return {"series": list_series_records(user_id="anonymous", is_admin=False)}


@app.post("/api/series", tags=["SaaS"])
async def api_create_series(req: SeriesCreateRequest, request: Request):
    auth = _resolve_caller_authorization(request)
    sb_user = auth.get("user")
    uid = sb_user["id"] if sb_user else ("admin" if auth["can_live_render"] else "anonymous")
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
        return record
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/jobs", tags=["SaaS"])
async def api_list_jobs(request: Request):
    auth = _resolve_caller_authorization(request)
    sb_user = auth.get("user")
    is_admin = bool(auth["mode"] == "studio_key" or (sb_user and sb_user.get("role") == "admin"))
    if is_admin:
        return {"jobs": list_job_records(limit=25, is_admin=True)}
    if sb_user:
        return {"jobs": list_job_records(limit=25, user_id=sb_user["id"], is_admin=False)}
    return {"jobs": list_job_records(limit=25, user_id="anonymous", is_admin=False)}


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

    # Enforce purchased language stream for non-admin customers
    sb_user = auth.get("user")
    if sb_user and sb_user.get("role") != "admin":
        user_plan = PRICING_PLANS.get(sb_user.get("plan_tier", ""), {})
        allowed_lang = user_plan.get("language_tier", "both")
        if allowed_lang == "urdu" and req.lang != "urdu":
            raise HTTPException(
                status_code=403,
                detail="Your plan is subscribed to the Urdu/Hindi Stream. Upgrade to English or Dual-Stream to render English episodes.",
            )
        if allowed_lang == "english" and req.lang != "english":
            raise HTTPException(
                status_code=403,
                detail="Your plan is subscribed to the English Stream. Upgrade to Dual-Stream Arbitrage to render both languages.",
            )

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

    # If authenticated via Supabase JWT, also persist to Supabase public.render_jobs
    # (which runs the PostgreSQL atomic credit-deduction trigger `enforce_render_job_credit_gate`).
    sb_user = auth.get("user")
    if sb_user and SUPABASE_URL and SUPABASE_ANON_KEY:
        try:
            sb_resp = requests.post(
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
                    "status": "queued",
                    "stage": "[0/6] Queued in Flow Worker Pool",
                    "progress": 5,
                    "concept": (req.custom_prompt or req.channel)[:160],
                },
                timeout=8,
            )
            if sb_resp.status_code >= 400:
                raise HTTPException(
                    status_code=402,
                    detail=f"Supabase Credit Gate: {sb_resp.text[:200]}",
                )
        except HTTPException:
            raise
        except Exception:
            pass

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
        await asyncio.to_thread(
            _http_session.patch,
            f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{sb_user['id']}",
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
        resp = await asyncio.to_thread(
            _http_session.patch,
            f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{sb_user['id']}",
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
        return _http_session.get(
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
    return {"customers": resp.json()}


@app.delete("/api/admin/customers/{user_id}", tags=["Admin"])
async def api_delete_customer(user_id: str, request: Request):
    """Deletes a customer account from Supabase Auth & cascades public.profiles (Founder Admin only)."""
    _require_founder_admin(request)
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=500, detail="Supabase service role key not configured")

    def _del_sync():
        return requests.delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
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

    plan = PRICING_PLANS.get(req.plan_tier)
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
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
        }
        user_id = None

        # 1. Check public.profiles first
        prof_check = _http_session.get(
            f"{SUPABASE_URL}/rest/v1/profiles?email=eq.{clean_email}&select=id,email",
            headers=headers,
            timeout=10,
        )
        if prof_check.status_code == 200 and prof_check.json():
            user_id = prof_check.json()[0]["id"]

        # 2. Create or update Auth user
        if not user_id:
            create_res = _http_session.post(
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
                users_res = _http_session.get(
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
        upd_auth = _http_session.put(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
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
        upsert_res = _http_session.post(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers={**headers, "Prefer": "resolution=merge-duplicates,return=representation"},
            json={
                "id": user_id,
                "email": clean_email,
                "full_name": clean_name,
                "role": "admin" if is_owner else "user",
                "plan_tier": req.plan_tier,
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
            "plan_tier": req.plan_tier,
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
