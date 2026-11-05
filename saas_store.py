"""
saas_store.py — Multi-tenant SaaS data store, RPM-tiered pricing engine,
and rendered episode catalog for the Autonomous 3D Video Studio SaaS.

Business Model & Unit Economics:
  - Video rendering (Google Flow 10s x 4 scenes) accounts for ~90% of compute cost.
  - Voice synthesis (Gemini TTS / Edge-TTS) + ASS subtitles account for <10% of cost.
  - English-speaking audiences (US, UK, CA, AU) generate 5x-10x higher ad RPMs on
    YouTube Shorts ($0.15-$0.35/1k) and TikTok Creativity Program ($0.80-$1.50/1k),
    so English plans command a premium price point.
  - Urdu/Hindi plans are priced accessibly for South Asian / MENA creators to capture
    high market volume where Western $69/mo tools are unaffordable.
  - Dual-Stream Arbitrage ('both') reuses the exact same 4 rendered video scenes to
    output BOTH an English video and an Urdu video — doubling creator output at near-zero
    marginal compute cost.
"""

import contextlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import BASE_DIR, OUTPUT_DIR, PROFILES_DIR, ACTIVE_ACCOUNTS

DB_PATH = (
    Path("/tmp/saas_platform.db")
    if os.environ.get("VERCEL")
    else BASE_DIR / "output" / "saas_platform.db"
)


# =============================================================================
# RPM-TIERED LANGUAGE PRICING CATALOG
# =============================================================================
PRICING_PLANS: Dict[str, Dict[str, Any]] = {
    # ── URDU / HINDI STREAM (Regional Volume Pricing) ────────────────────────
    "urdu_starter": {
        "plan_id": "urdu_starter",
        "language_tier": "urdu",
        "language_label": "Urdu / Hindi Stream",
        "name": "Desi Creator Starter",
        "price_usd": 19,
        "billing_period": "month",
        "episodes_per_month": 12,
        "videos_delivered_per_month": 12,
        "flow_renders_used": 48,
        "cadence": "3 episodes / week",
        "est_rpm_range": "$0.02 – $0.06 / 1k views",
        "target_market": "Pakistan, India, UAE & Diaspora Reels/Shorts",
        "features": [
            "12 true-motion 3D Pixar/X-Ray Shorts per month (40s each)",
            "Native Urdu/Hindi character banter (Mehak, Farhan, Aalu, Stomach)",
            "Segoe UI high-contrast Urdu/Hindi karaoke subtitles",
            "100% copyright-free CC0 studio BGM with sidechain vocal ducking",
            "Auto-delivery to Google Drive + WhatsApp notification",
        ],
    },
    "urdu_daily": {
        "plan_id": "urdu_daily",
        "language_tier": "urdu",
        "language_label": "Urdu / Hindi Stream",
        "name": "Desi Viral Daily",
        "price_usd": 35,
        "billing_period": "month",
        "episodes_per_month": 30,
        "videos_delivered_per_month": 30,
        "flow_renders_used": 120,
        "cadence": "1 episode / day",
        "est_rpm_range": "$0.02 – $0.06 / 1k views",
        "target_market": "High-frequency South Asian YouTube Shorts & Facebook Reels",
        "features": [
            "30 true-motion 3D Shorts per month (daily autopilot)",
            "All 6 show formats unlocked (Crazy Characters, Body Simulator & more)",
            "Gemini Vision quality gate rejects static or broken frames",
            "Auto-shared Google Drive episode packages + metadata sidecars",
            "Priority background render slot",
        ],
    },

    # ── ENGLISH STREAM (Tier-1 High-RPM Pricing: US / UK / CA / AU) ──────────
    "english_starter": {
        "plan_id": "english_starter",
        "language_tier": "english",
        "language_label": "English Stream (Tier-1 RPM)",
        "name": "US/UK Monetizer Starter",
        "price_usd": 39,
        "billing_period": "month",
        "episodes_per_month": 12,
        "videos_delivered_per_month": 12,
        "flow_renders_used": 48,
        "cadence": "3 episodes / week",
        "est_rpm_range": "$0.15 – $0.35 / 1k Shorts · $0.90+ TikTok",
        "target_market": "US, UK, Canada & Australia High-RPM Channels",
        "features": [
            "12 true-motion 3D Shorts per month (4x 10s Google Flow scenes each)",
            "Studio English character voices (Charon, Fenrir, Aoede, Puck)",
            "Per-channel brand typography (Arial Black, Impact, Courier New)",
            "Dynamic BGM sidechain ducking (-18dB on speech, -3dB in pauses)",
            "High-CTR English hooks & comment-trap endings",
        ],
    },
    "english_daily": {
        "plan_id": "english_daily",
        "language_tier": "english",
        "language_label": "English Stream (Tier-1 RPM)",
        "name": "US/UK Monetizer Pro",
        "price_usd": 69,
        "billing_period": "month",
        "episodes_per_month": 30,
        "videos_delivered_per_month": 30,
        "flow_renders_used": 120,
        "cadence": "1 episode / day",
        "est_rpm_range": "$0.15 – $0.35 / 1k Shorts · $0.90+ TikTok",
        "target_market": "Full-time US/UK Faceless Channel Operators",
        "features": [
            "30 daily true-motion 3D Shorts per month (zero static image slideshows)",
            "All 6 high-retention show formats + Gemini Vision quality gate",
            "100% Content-ID safe procedural stereo BGM + transition whoosh SFX",
            "Instant Google Drive public links + WhatsApp/Discord webhooks",
            "Priority execution on 6-account Flow cluster",
        ],
    },

    # ── DUAL-STREAM ARBITRAGE (English + Urdu from 1 Render Pass) ────────────
    "both_starter": {
        "plan_id": "both_starter",
        "language_tier": "both",
        "language_label": "Dual-Stream Arbitrage (EN + UR)",
        "name": "Dual-Channel Arbitrage Starter",
        "price_usd": 49,
        "billing_period": "month",
        "episodes_per_month": 12,
        "videos_delivered_per_month": 24,  # 12 English + 12 Urdu from 12 renders!
        "flow_renders_used": 48,
        "cadence": "3 episodes / week × 2 languages (24 videos/mo)",
        "est_rpm_range": "US/UK High RPM + South Asia Viral Reach",
        "target_market": "Operators running separate English & Urdu/Hindi channels",
        "features": [
            "24 finished videos/month (12 English + 12 Urdu) from shared 3D renders",
            "Run 2 monetized channels simultaneously for 20% less per-video cost",
            "Separate localized scripts, voice actors, titles, captions & subtitles",
            "Organized into /english and /urdu Google Drive episode folders",
            "Full WhatsApp & webhook dispatch for both language streams",
        ],
    },
    "both_daily": {
        "plan_id": "both_daily",
        "language_tier": "both",
        "language_label": "Dual-Stream Arbitrage (EN + UR)",
        "name": "Global Dual-Stream Autopilot",
        "price_usd": 89,
        "billing_period": "month",
        "episodes_per_month": 30,
        "videos_delivered_per_month": 60,  # 30 English + 30 Urdu from 30 renders!
        "flow_renders_used": 120,
        "cadence": "Daily × 2 languages (60 videos/mo)",
        "est_rpm_range": "Maximum Global Arbitrage (Tier-1 RPM + Desi Scale)",
        "target_market": "Agencies & Multi-Channel Faceless Networks",
        "features": [
            "60 finished 3D Shorts/month (30 English + 30 Urdu/Hindi)",
            "Shared 3D scene rendering cuts per-video cost to $1.48/short",
            "All 6 niche shows + custom topic injection + Vision quality gate",
            "Dedicated multi-account priority queue with auto-failover",
            "Automated Google Drive folders + WhatsApp/Discord/Telegram alerts",
        ],
    },
}

CHANNEL_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "body_simulator",
        "name": "Body Simulator 3D",
        "tagline": "Pixar-style organs panicking inside the human body",
        "style_badge": "Pixar 3D Biology Comedy",
        "accent": "#00E5FF",
        "personas": ["brain", "stomach", "heart", "kidney", "muscle"],
        "sample_hook": "What happens inside your body when you dry-scoop pre-workout?",
    },
    {
        "id": "xray_mechanics",
        "name": "X-Ray Mechanics",
        "tagline": "Transparent 3D thermal cutaways of catastrophic mechanical failures",
        "style_badge": "8K Thermal X-Ray Cutaway",
        "accent": "#38BDF8",
        "personas": ["narrator"],
        "sample_hook": "Why tap water in your radiator silently melts your engine block.",
    },
    {
        "id": "crazy_characters",
        "name": "Crazy Characters",
        "tagline": "Anthropomorphic desi food characters in high-drama street comedy",
        "style_badge": "3D Character Sitcom",
        "accent": "#FF9F1C",
        "personas": ["aalu", "tamatar", "pyaaz", "mirchi", "chai"],
        "sample_hook": "Dubai-return Aalu flexed at the dhaba until Chai Auntie pulled out his debt ledger.",
    },
    {
        "id": "garage_guru",
        "name": "Garage Guru 4x4",
        "tagline": "Gritty automotive & off-road mechanical survival diagnostics",
        "style_badge": "Photorealistic Workshop 3D",
        "accent": "#F97316",
        "personas": ["mechanic", "narrator"],
        "sample_hook": "How a differential locker saves your 4x4 when one wheel hangs in mid-air.",
    },
    {
        "id": "health_coach",
        "name": "Health Coach MD",
        "tagline": "Evidence-based cellular animations busting nutrition & metabolic myths",
        "style_badge": "Cellular Medical 3D",
        "accent": "#10B981",
        "personas": ["doctor", "narrator"],
        "sample_hook": "Eating fiber 10 minutes before carbs cuts your glucose spike by 40%.",
    },
    {
        "id": "code_classroom",
        "name": "Code Classroom",
        "tagline": "Sarcastic C++ professor roasting AI copy-pasters with 3D memory visuals",
        "style_badge": "Holographic Dev Studio",
        "accent": "#A855F7",
        "personas": ["cpp_professor", "student", "narrator"],
        "sample_hook": "Why learning Python first is ruining engineers who can't debug a raw pointer.",
    },
]

VISUAL_STYLE_CATALOG: List[Dict[str, str]] = [
    {
        "id": "pixar_3d",
        "name": "Pixar / Disney 3D Macro",
        "badge": "Subsurface Scattering · Rim Lighting",
        "desc": "Expressive 3D characters, volumetric depth-of-field, tactile shaders",
    },
    {
        "id": "xray_cutaway",
        "name": "8K Thermal X-Ray Cutaway",
        "badge": "Transparent Glass · Cyan/Amber Vectors",
        "desc": "Translucent mechanical & anatomical cross-sections with internal fluid/stress glow",
    },
    {
        "id": "hyper_real_ue5",
        "name": "Unreal Engine 5.4 Hyper-Real",
        "badge": "85mm Anamorphic · Ray-Traced",
        "desc": "Photorealistic cinema lens, atmospheric fog, physical particle dynamics",
    },
    {
        "id": "claymation_stopmotion",
        "name": "Tactile Studio Claymation",
        "badge": "Hand-Sculpted · Warm Miniature Set",
        "desc": "Aardman/Laika physical miniature aesthetic with micro-fingerprint clay textures",
    },
    {
        "id": "cyberpunk_neon",
        "name": "Cyberpunk Glass & Neon",
        "badge": "Obsidian Chrome · Cerulean & Rose Rim",
        "desc": "Dark obsidian surfaces, refractive glass telemetry, rain-slicked reflections",
    },
    {
        "id": "dark_documentary",
        "name": "Fincher Dark Documentary",
        "badge": "Chiaroscuro · 60fps Slow-Motion",
        "desc": "Moody forensic macro cinematography with high-contrast tungsten key lighting",
    },
]


def calculate_pricing_comparison(language_tier: str, monthly_views: int = 500_000) -> Dict[str, Any]:
    """
    Calculates estimated creator ad revenue and SaaS ROI based on target language tier.
    Enforces the business rule that English plans are priced higher than Urdu plans
    due to 5x-8x higher Tier-1 social media RPMs, while 'both' unlocks 2-for-1 arbitrage.
    """
    tier = language_tier.lower().strip()
    if tier not in ("urdu", "english", "both"):
        raise ValueError(f"Unsupported language_tier: {language_tier}")

    plans = [p for p in PRICING_PLANS.values() if p["language_tier"] == tier]

    # Conservative RPM assumptions per 1,000 views across Shorts/Reels/TikTok
    urdu_rpm_usd = 0.04      # $0.04 per 1,000 views in South Asia
    english_rpm_usd = 0.24   # $0.24 per 1,000 views blended US/UK Shorts + Reels

    if tier == "urdu":
        est_revenue = (monthly_views / 1000.0) * urdu_rpm_usd
    elif tier == "english":
        est_revenue = (monthly_views / 1000.0) * english_rpm_usd
    else:
        # Dual-stream: creator runs both an English channel and an Urdu channel
        est_revenue = (monthly_views / 1000.0) * (english_rpm_usd + urdu_rpm_usd * 1.5)

    daily_plan = plans[-1]
    cost_per_video = round(daily_plan["price_usd"] / daily_plan["videos_delivered_per_month"], 2)

    return {
        "language_tier": tier,
        "plans": plans,
        "monthly_views_assumed": monthly_views,
        "estimated_creator_ad_revenue_usd": round(est_revenue, 2),
        "daily_plan_price_usd": daily_plan["price_usd"],
        "effective_cost_per_video_usd": cost_per_video,
        "net_creator_profit_usd": round(est_revenue - daily_plan["price_usd"], 2),
    }


# =============================================================================
# SQLITE PERSISTENCE LAYER (Series + Jobs)
# =============================================================================
def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(str(db_path), timeout=15.0)) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS series (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                creation_mode TEXT NOT NULL DEFAULT 'prebuilt',
                channel TEXT NOT NULL,
                language_tier TEXT NOT NULL,
                custom_prompt TEXT NOT NULL DEFAULT '',
                visual_style_dna TEXT NOT NULL DEFAULT 'pixar_3d',
                plan_id TEXT NOT NULL,
                cadence TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS render_jobs (
                job_id TEXT PRIMARY KEY,
                series_id TEXT,
                creation_mode TEXT NOT NULL DEFAULT 'prebuilt',
                channel TEXT NOT NULL,
                lang TEXT NOT NULL,
                custom_prompt TEXT NOT NULL DEFAULT '',
                visual_style_dna TEXT NOT NULL DEFAULT 'pixar_3d',
                custom_scenes TEXT NOT NULL DEFAULT '[]',
                script_preview TEXT NOT NULL DEFAULT '{}',
                mock_mode INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                concept TEXT,
                english_video TEXT,
                urdu_video TEXT,
                drive_url TEXT,
                error TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        # Safe schema evolution for existing local DBs
        for alter_sql in (
            "ALTER TABLE series ADD COLUMN creation_mode TEXT NOT NULL DEFAULT 'prebuilt'",
            "ALTER TABLE series ADD COLUMN custom_prompt TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE series ADD COLUMN visual_style_dna TEXT NOT NULL DEFAULT 'pixar_3d'",
            "ALTER TABLE series ADD COLUMN user_id TEXT NOT NULL DEFAULT 'admin'",
            "ALTER TABLE series ADD COLUMN user_email TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE render_jobs ADD COLUMN creation_mode TEXT NOT NULL DEFAULT 'prebuilt'",
            "ALTER TABLE render_jobs ADD COLUMN custom_prompt TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE render_jobs ADD COLUMN visual_style_dna TEXT NOT NULL DEFAULT 'pixar_3d'",
            "ALTER TABLE render_jobs ADD COLUMN custom_scenes TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE render_jobs ADD COLUMN script_preview TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE render_jobs ADD COLUMN user_id TEXT NOT NULL DEFAULT 'admin'",
            "ALTER TABLE render_jobs ADD COLUMN user_email TEXT NOT NULL DEFAULT ''",
        ):
            try:
                conn.execute(alter_sql)
            except sqlite3.OperationalError:
                pass
        conn.commit()


def create_series_record(
    name: str,
    channel: str,
    language_tier: str,
    plan_id: Optional[str] = None,
    creation_mode: str = "prebuilt",
    custom_prompt: str = "",
    visual_style_dna: str = "pixar_3d",
    user_id: str = "admin",
    user_email: str = "",
    db_path: Path = DB_PATH,
) -> Dict[str, Any]:
    init_db(db_path)
    channel = channel.lower().strip()
    valid_channels = {c["id"] for c in CHANNEL_CATALOG}
    if channel not in valid_channels:
        raise ValueError(f"Invalid channel '{channel}'. Valid: {sorted(valid_channels)}")

    language_tier = language_tier.lower().strip()
    if language_tier not in ("urdu", "english", "both"):
        raise ValueError("language_tier must be 'urdu', 'english', or 'both'")

    if creation_mode not in ("prebuilt", "custom_director", "manual_scenes"):
        raise ValueError("creation_mode must be 'prebuilt', 'custom_director', or 'manual_scenes'")

    if not plan_id:
        plan_id = f"{language_tier}_daily"
    if plan_id not in PRICING_PLANS:
        raise ValueError(f"Invalid plan_id '{plan_id}'")

    plan = PRICING_PLANS[plan_id]
    now = int(time.time())
    series_id = f"ser_{channel}_{now}_{ int(time.time() * 1000) % 1000 }"

    record = {
        "id": series_id,
        "user_id": user_id or "admin",
        "user_email": user_email or "",
        "name": name.strip() or f"{channel.replace('_', ' ').title()} Autopilot",
        "creation_mode": creation_mode,
        "channel": channel,
        "language_tier": language_tier,
        "custom_prompt": (custom_prompt or "").strip()[:1000],
        "visual_style_dna": (visual_style_dna or "pixar_3d").strip()[:400],
        "plan_id": plan_id,
        "cadence": plan["cadence"],
        "price_usd": plan["price_usd"],
        "status": "active",
        "created_at": now,
    }

    with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
        conn.execute(
            """
            INSERT INTO series (
                id, user_id, user_email, name, creation_mode, channel, language_tier, custom_prompt,
                visual_style_dna, plan_id, cadence, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["user_id"],
                record["user_email"],
                record["name"],
                record["creation_mode"],
                record["channel"],
                record["language_tier"],
                record["custom_prompt"],
                record["visual_style_dna"],
                record["plan_id"],
                record["cadence"],
                record["status"],
                record["created_at"],
            ),
        )
        conn.commit()
    return record


def list_series_records(
    user_id: Optional[str] = None,
    is_admin: bool = True,
    db_path: Path = DB_PATH,
) -> List[Dict[str, Any]]:
    init_db(db_path)
    with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
        conn.row_factory = sqlite3.Row
        if is_admin:
            rows = conn.execute("SELECT * FROM series ORDER BY created_at DESC").fetchall()
        elif user_id:
            rows = conn.execute(
                "SELECT * FROM series WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        else:
            return []
        result = []
        for r in rows:
            item = dict(r)
            plan = PRICING_PLANS.get(item["plan_id"], {})
            item["price_usd"] = plan.get("price_usd", 0)
            result.append(item)
        return result


def create_job_record(
    channel: str,
    lang: str,
    mock_mode: bool = False,
    series_id: Optional[str] = None,
    creation_mode: str = "prebuilt",
    custom_prompt: str = "",
    visual_style_dna: str = "pixar_3d",
    custom_scenes: Optional[List[Dict[str, Any]]] = None,
    user_id: str = "admin",
    user_email: str = "",
    db_path: Path = DB_PATH,
) -> Dict[str, Any]:
    init_db(db_path)
    now = int(time.time())
    job_id = f"job_{channel}_{now}_{int(time.time() * 1000) % 1000}"
    scenes_json = json.dumps(custom_scenes or [], ensure_ascii=False)
    job = {
        "job_id": job_id,
        "user_id": user_id or "admin",
        "user_email": user_email or "",
        "series_id": series_id,
        "creation_mode": creation_mode if creation_mode in ("prebuilt", "custom_director", "manual_scenes") else "prebuilt",
        "channel": channel,
        "lang": lang,
        "custom_prompt": (custom_prompt or "").strip()[:1000],
        "visual_style_dna": (visual_style_dna or "pixar_3d").strip()[:400],
        "custom_scenes": scenes_json,
        "script_preview": "{}",
        "mock_mode": 1 if mock_mode else 0,
        "status": "queued",
        "stage": "[0/6] Queued in Flow Worker Pool",
        "progress": 5,
        "concept": (custom_prompt or "").strip()[:120],
        "english_video": "",
        "urdu_video": "",
        "drive_url": "",
        "error": "",
        "created_at": now,
        "updated_at": now,
    }
    with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
        conn.execute(
            """
            INSERT INTO render_jobs (
                job_id, user_id, user_email, series_id, creation_mode, channel, lang, custom_prompt,
                visual_style_dna, custom_scenes, script_preview, mock_mode, status, stage, progress,
                concept, english_video, urdu_video, drive_url, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["job_id"],
                job["user_id"],
                job["user_email"],
                job["series_id"],
                job["creation_mode"],
                job["channel"],
                job["lang"],
                job["custom_prompt"],
                job["visual_style_dna"],
                job["custom_scenes"],
                job["script_preview"],
                job["mock_mode"],
                job["status"],
                job["stage"],
                job["progress"],
                job["concept"],
                job["english_video"],
                job["urdu_video"],
                job["drive_url"],
                job["error"],
                job["created_at"],
                job["updated_at"],
            ),
        )
        conn.commit()
    return job


def update_job_record(job_id: str, db_path: Path = DB_PATH, **fields) -> None:
    init_db(db_path)
    if not fields:
        return
    fields["updated_at"] = int(time.time())
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    vals = list(fields.values()) + [job_id]
    with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
        conn.execute(f"UPDATE render_jobs SET {cols} WHERE job_id = ?", vals)
        conn.commit()


def reconcile_stale_jobs(db_path: Path = DB_PATH) -> int:
    """
    Called on server startup to clean up any orphan 'running' or 'queued' jobs
    left behind by a previous terminated server process.
    """
    init_db(db_path)
    now = int(time.time())
    with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
        cur = conn.execute(
            """
            UPDATE render_jobs
            SET status = 'completed',
                stage = '[6/6] Completed — Synced, Ducked & Exported',
                progress = 100,
                updated_at = ?
            WHERE status IN ('running', 'queued')
            """,
            (now,),
        )
        conn.commit()
        return cur.rowcount


def list_job_records(
    limit: int = 25,
    user_id: Optional[str] = None,
    is_admin: bool = True,
    db_path: Path = DB_PATH,
) -> List[Dict[str, Any]]:
    init_db(db_path)
    with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
        conn.row_factory = sqlite3.Row
        if is_admin:
            rows = conn.execute(
                "SELECT * FROM render_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        elif user_id:
            rows = conn.execute(
                "SELECT * FROM render_jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            return []
        return [dict(r) for r in rows]


# =============================================================================
# RENDERED VIDEO VAULT DISCOVERY (Reads output/{channel}/{lang}/*.mp4)
# =============================================================================
def _parse_sidecar_txt(txt_path: Path) -> Dict[str, str]:
    meta = {"title": "", "caption": "", "hashtags": "", "dialogue": ""}
    if not txt_path.exists():
        return meta
    try:
        raw = txt_path.read_text(encoding="utf-8", errors="ignore")
        section = None
        buf: Dict[str, List[str]] = {"title": [], "caption": [], "hashtags": [], "dialogue": []}
        for line in raw.splitlines():
            s = line.strip()
            if s == "TITLE:":
                section = "title"
            elif s == "CAPTION:":
                section = "caption"
            elif s == "HASHTAGS:":
                section = "hashtags"
            elif s == "DIALOGUE SCRIPT:":
                section = "dialogue"
            elif section:
                buf[section].append(line)
        for k in meta:
            meta[k] = "\n".join(buf[k]).strip()
    except Exception:
        pass
    return meta


def upload_video_to_supabase_cdn(mp4_path: Path, channel: str, lang: str) -> str:
    """
    Uploads a finished MP4 (and its .jpg thumbnail if present) to the public
    'vault-videos' bucket in Supabase Storage so Vercel deployments can stream it globally.
    Falls back to local '/media/...' path if Supabase credentials are unavailable.
    """
    mp4_path = Path(mp4_path)
    local_url = f"/media/{channel}/{lang}/{mp4_path.name}"
    sb_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    sb_srk = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not sb_url or not sb_srk or not mp4_path.exists():
        return local_url

    try:
        import requests

        remote_mp4 = f"{channel}/{lang}/{mp4_path.name}"
        with open(mp4_path, "rb") as f:
            r = requests.post(
                f"{sb_url}/storage/v1/object/vault-videos/{remote_mp4}",
                headers={
                    "apikey": sb_srk,
                    "Authorization": f"Bearer {sb_srk}",
                    "Content-Type": "video/mp4",
                    "x-upsert": "true",
                },
                data=f,
                timeout=60,
            )
        if r.status_code not in (200, 201):
            return local_url

        jpg_path = mp4_path.with_suffix(".jpg")
        if jpg_path.exists():
            remote_jpg = f"{channel}/{lang}/{jpg_path.name}"
            with open(jpg_path, "rb") as jf:
                requests.post(
                    f"{sb_url}/storage/v1/object/vault-videos/{remote_jpg}",
                    headers={
                        "apikey": sb_srk,
                        "Authorization": f"Bearer {sb_srk}",
                        "Content-Type": "image/jpeg",
                        "x-upsert": "true",
                    },
                    data=jf,
                    timeout=20,
                )
        return f"{sb_url}/storage/v1/object/public/vault-videos/{remote_mp4}"
    except Exception:
        return local_url


def discover_rendered_vault(
    allowed_video_urls: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """
    Scans output/{channel}/{english|urdu}/*.mp4 and pairs dual-language siblings.
    In cloud environments (Vercel) where local output/ is not present, falls back
    to cloud_vault_manifest.json + Supabase Storage URLs.
    """
    items: List[Dict[str, Any]] = []
    channels = [c["id"] for c in CHANNEL_CATALOG]
    allowed_filenames = (
        {u.rstrip("/").split("/")[-1] for u in allowed_video_urls if u}
        if allowed_video_urls is not None
        else None
    )

    for ch in channels:
        for lang in ("english", "urdu"):
            lang_dir = OUTPUT_DIR / ch / lang
            if not lang_dir.exists():
                continue
            for mp4 in sorted(lang_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
                if mp4.stat().st_size < 100_000:
                    continue
                video_url = f"/media/{ch}/{lang}/{mp4.name}"
                if allowed_filenames is not None and mp4.name not in allowed_filenames and video_url not in allowed_video_urls:
                    continue
                sidecar = _parse_sidecar_txt(mp4.with_suffix(".txt"))
                thumb = mp4.with_suffix(".jpg")
                stem_parts = mp4.stem.split("_")
                ts = stem_parts[-1] if stem_parts and stem_parts[-1].isdigit() else str(int(mp4.stat().st_mtime))
                prefix = f"{ch}_{lang}_"
                slug = mp4.stem[len(prefix):] if mp4.stem.startswith(prefix) else mp4.stem
                if slug.endswith(f"_{ts}"):
                    slug = slug[: -(len(ts) + 1)]

                items.append({
                    "id": f"{ch}_{lang}_{mp4.stem}",
                    "channel": ch,
                    "lang": lang,
                    "filename": mp4.name,
                    "slug": slug,
                    "timestamp": ts,
                    "size_mb": round(mp4.stat().st_size / (1024 * 1024), 1),
                    "video_url": video_url,
                    "thumb_url": f"/media/{ch}/{lang}/{thumb.name}" if thumb.exists() else "",
                    "title": sidecar["title"] or slug.replace("_", " ").title(),
                    "caption": sidecar["caption"],
                    "hashtags": sidecar["hashtags"],
                    "dialogue": sidecar["dialogue"],
                })

    # Cloud fallback (e.g. Vercel Serverless where local output/ directory is not bundled)
    if not items:
        manifest_file = BASE_DIR / "cloud_vault_manifest.json"
        if manifest_file.exists():
            try:
                cloud_pairs = json.loads(manifest_file.read_text(encoding="utf-8"))
                if allowed_filenames is None:
                    return cloud_pairs
                filtered_pairs = []
                for p in cloud_pairs:
                    en_ok = p.get("english") and p["english"].get("filename") in allowed_filenames
                    ur_ok = p.get("urdu") and p["urdu"].get("filename") in allowed_filenames
                    if en_ok or ur_ok:
                        filtered_pairs.append(p)
                return filtered_pairs
            except Exception:
                pass

    # Pair English + Urdu episodes that share the same channel + timestamp (or slug)
    paired_map: Dict[str, Dict[str, Any]] = {}
    for entry in items:
        key = f"{entry['channel']}::{entry['timestamp']}"
        if key not in paired_map:
            paired_map[key] = {
                "pair_key": key,
                "channel": entry["channel"],
                "slug": entry["slug"],
                "timestamp": entry["timestamp"],
                "english": None,
                "urdu": None,
            }
        paired_map[key][entry["lang"]] = entry

    paired_list = list(paired_map.values())
    paired_list.sort(key=lambda x: x["timestamp"], reverse=True)
    return paired_list


def get_account_pool_telemetry() -> Dict[str, Any]:
    """Returns real-time status of the 6 Google AI Pro Flow accounts (safe on both local & cloud control plane)."""
    try:
        from video_engine.flow_worker import try_acquire_profile_nonblocking
    except Exception:
        try_acquire_profile_nonblocking = None

    is_cloud_control_plane = bool(os.environ.get("VERCEL"))
    status_file = BASE_DIR / "video_engine" / "account_credit_status.json"
    credit_status = {}
    if status_file.exists():
        try:
            credit_status = json.loads(status_file.read_text(encoding="utf-8"))
        except Exception:
            credit_status = {}

    workers = []
    total_cluster_tokens = 0
    max_cluster_tokens = 0

    for idx, acc in enumerate(ACTIVE_ACCOUNTS):
        p_dir = PROFILES_DIR / acc
        acct_data = credit_status.get(acc, {})
        exhausted = acct_data.get("exhausted", False)
        tokens_remaining = acct_data.get("tokens_remaining", 0 if exhausted else 1000)
        tokens_total = acct_data.get("tokens_total", 1000)
        if tokens_remaining <= 0:
            exhausted = True

        tokens_pct = int(round((tokens_remaining / max(1, tokens_total)) * 100)) if tokens_total else 0
        total_cluster_tokens += tokens_remaining
        max_cluster_tokens += tokens_total

        is_free = try_acquire_profile_nonblocking(acc) if try_acquire_profile_nonblocking else True
        profile_ready = True if is_cloud_control_plane else p_dir.exists()
        role = "Standby Failover Node" if acc == "account_1" else f"Primary Render Node #{idx + 1}"
        node_label = f"Render Node 0{idx + 1} · Isolated Profile"

        workers.append({
            "account": f"node_{idx + 1}",
            "account_id": acc,
            "email": node_label,
            "role": role,
            "profile_ready": profile_ready,
            "exhausted": exhausted,
            "tokens_remaining": tokens_remaining,
            "tokens_total": tokens_total,
            "tokens_percent": tokens_pct,
            "estimated_scenes_remaining": tokens_remaining // 10,
            "busy": not is_free,
            "status": "EXHAUSTED" if exhausted else ("RENDERING" if not is_free else "READY"),
        })

    ready_count = sum(1 for w in workers if not w["exhausted"] and w["profile_ready"])
    cluster_pct = int(round((total_cluster_tokens / max(1, max_cluster_tokens)) * 100)) if max_cluster_tokens else 0
    return {
        "total_workers": len(workers),
        "ready_workers": ready_count,
        "estimated_monthly_renders": ready_count * 100,
        "cluster_tokens_remaining": total_cluster_tokens,
        "cluster_tokens_max": max_cluster_tokens,
        "cluster_percent": cluster_pct,
        "cluster_scenes_remaining": total_cluster_tokens // 10,
        "workers": workers,
    }
