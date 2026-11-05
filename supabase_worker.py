"""
supabase_worker.py — Private Local Playwright & Google Flow Worker Daemon
==========================================================================
Connects to the dedicated VoxFlow Studio Supabase project (ouqjlqqgnboytjvudylv)
using SUPABASE_SERVICE_ROLE_KEY.

Architecture (Split Control-Plane / Private Worker-Plane):
  1. Public web users sign up / log in via Supabase Auth on Vercel or the web UI.
  2. When a user queues a render job in `public.render_jobs`, the PostgreSQL
     BEFORE INSERT trigger (`enforce_render_job_credit_gate`) atomically verifies
     that:
       - If `mock_mode = false` (live Google Flow + Playwright render), the user
         MUST have `role = 'admin'` OR `credits_balance > 0` (and decrements 1 credit).
       - If `mock_mode = true` (sandbox simulation), decrements `sandbox_runs_remaining`.
  3. This private daemon runs ONLY on Ammar's local machine (where Chrome profiles
     `account_1..6` and `.env` reside), polls `public.render_jobs` for `status = 'queued'`,
     executes the job, and streams real-time progress back to Supabase.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ROOT_DIR = Path(__file__).parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config  # loads .env into os.environ
from multi_channel_agent import produce_dual_language_episode
from saas_store import upload_video_to_supabase_cdn

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ouqjlqqgnboytjvudylv.supabase.co").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _supabase_headers(prefer: str = "return=representation") -> Dict[str, str]:
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured in .env")
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def fetch_queued_supabase_jobs(limit: int = 5) -> List[Dict[str, Any]]:
    """Polls public.render_jobs for jobs with status = 'queued' ordered FIFO."""
    url = (
        f"{SUPABASE_URL}/rest/v1/render_jobs"
        f"?status=eq.queued&order=created_at.asc&limit={limit}"
    )
    resp = requests.get(url, headers=_supabase_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def update_supabase_job(job_uuid: str, **fields) -> Dict[str, Any]:
    """Updates a row in public.render_jobs by its UUID primary key."""
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    url = f"{SUPABASE_URL}/rest/v1/render_jobs?id=eq.{job_uuid}"
    resp = requests.patch(url, headers=_supabase_headers(), json=fields, timeout=15)
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else {}


def claim_supabase_job(job_uuid: str) -> Optional[Dict[str, Any]]:
    """Atomically claims a queued job by transitioning status queued -> running."""
    url = f"{SUPABASE_URL}/rest/v1/render_jobs?id=eq.{job_uuid}&status=eq.queued"
    payload = {
        "status": "running",
        "stage": "[1/6] Claimed by Local Flow Worker Cluster — Initializing AI Director...",
        "progress": 15,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    resp = requests.patch(url, headers=_supabase_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


async def process_supabase_job(job: Dict[str, Any]) -> None:
    """Executes a single claimed Supabase render_job row."""
    job_uuid = job["id"]
    job_code = job.get("job_code", job_uuid[:8])
    user_id = job.get("user_id", "")
    channel = job.get("channel") or "body_simulator"
    lang = job.get("lang") or "both"
    mock_mode = bool(job.get("mock_mode", False))
    creation_mode = job.get("creation_mode") or "prebuilt"
    custom_prompt = (job.get("custom_prompt") or "").strip()
    visual_style = (job.get("visual_style_dna") or "pixar_3d").strip()
    raw_scenes = job.get("custom_scenes") or []
    if isinstance(raw_scenes, str):
        try:
            raw_scenes = json.loads(raw_scenes)
        except Exception:
            raw_scenes = []

    # Resolve user's isolated WhatsApp credentials from public.profiles
    wa_token, wa_user_id, is_admin_owner = "", "", False
    if user_id:
        try:
            prof_res = requests.get(
                f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}&select=role,wa_agent_token,wa_user_id,wa_verified",
                headers=_supabase_headers(),
                timeout=8,
            )
            if prof_res.status_code == 200 and prof_res.json():
                prof = prof_res.json()[0]
                is_admin_owner = prof.get("role") == "admin"
                if prof.get("wa_verified") and prof.get("wa_agent_token") and prof.get("wa_user_id"):
                    wa_token = prof["wa_agent_token"]
                    wa_user_id = prof["wa_user_id"]
        except Exception:
            pass

    print(
        f"\n🚀 [SUPABASE WORKER] Processing Job {job_code} | Mode: {creation_mode} "
        f"| Channel: {channel} | Lang: {lang} | Mock: {mock_mode}"
    )

    def _on_progress(stage: str, progress: int, concept: str = None, script_preview: dict = None):
        patch_data: Dict[str, Any] = {"stage": stage, "progress": progress}
        if concept:
            patch_data["concept"] = concept[:200]
        if script_preview:
            patch_data["script_preview"] = script_preview
        try:
            update_supabase_job(job_uuid, **patch_data)
        except Exception as exc:
            print(f"   ⚠️ Telemetry patch warning: {exc}")

    try:
        render_task = asyncio.create_task(
            produce_dual_language_episode(
                channel=channel,
                mock_video=mock_mode,
                max_scenes=4,
                target_lang=lang,
                custom_prompt=custom_prompt if creation_mode in ("custom_director", "manual_scenes") else None,
                visual_style=visual_style,
                custom_scenes=raw_scenes if creation_mode == "manual_scenes" else None,
                progress_callback=_on_progress,
                wa_token=wa_token,
                wa_user_id=wa_user_id,
                allow_owner_wa_fallback=is_admin_owner,
            )
        )

        async def _watch_cancellation():
            while not render_task.done():
                await asyncio.sleep(3.0)
                try:
                    st_res = await asyncio.to_thread(
                        requests.get,
                        f"{SUPABASE_URL}/rest/v1/render_jobs?id=eq.{job_uuid}&select=status",
                        headers=_supabase_headers(),
                        timeout=6,
                    )
                    if st_res.status_code == 200 and st_res.json():
                        if st_res.json()[0].get("status") == "cancelled":
                            print(f"🛑 [SUPABASE WORKER] Job {job_code} cancelled by user — halting pipeline...")
                            render_task.cancel()
                            return
                except Exception:
                    pass

        watcher = asyncio.create_task(_watch_cancellation())
        try:
            urdu_final, english_final = await render_task
        finally:
            watcher.cancel()

        en_url = (
            await asyncio.to_thread(upload_video_to_supabase_cdn, Path(english_final), channel, "english")
            if english_final
            else ""
        )
        ur_url = (
            await asyncio.to_thread(upload_video_to_supabase_cdn, Path(urdu_final), channel, "urdu")
            if urdu_final
            else ""
        )

        update_supabase_job(
            job_uuid,
            status="completed",
            stage="[6/6] Completed — 3D Video Synced, Ducked & Exported",
            progress=100,
            english_video=en_url,
            urdu_video=ur_url,
        )
        print(f"✅ [SUPABASE WORKER] Completed Job {job_code} -> EN: {en_url} | UR: {ur_url}")

    except asyncio.CancelledError:
        print(f"🛑 [SUPABASE WORKER] Job {job_code} halted cleanly after user cancellation.")
        try:
            update_supabase_job(job_uuid, status="cancelled", stage="Cancelled by user", error="")
        except Exception:
            pass
    except Exception as exc:
        err_msg = str(exc)[:300]
        print(f"❌ [SUPABASE WORKER] Failed Job {job_code}: {err_msg}")
        try:
            update_supabase_job(
                job_uuid,
                status="failed",
                stage="Pipeline halted with error",
                error=err_msg,
            )
        except Exception:
            pass


async def run_worker_loop(poll_interval: float = 4.0, once: bool = False) -> None:
    print("=" * 78)
    print(" 🔒 VOXFLOW STUDIO — PRIVATE SUPABASE WORKER DAEMON")
    print(f"    Supabase Project : {SUPABASE_URL}")
    print(f"    Poll Interval    : {poll_interval}s")
    print("=" * 78)

    while True:
        try:
            queued_jobs = fetch_queued_supabase_jobs(limit=3)
            for item in queued_jobs:
                claimed = claim_supabase_job(item["id"])
                if claimed:
                    await process_supabase_job(claimed)
        except Exception as e:
            print(f"[Worker Poll Warning] {e}")

        if once:
            break
        await asyncio.sleep(poll_interval)


def main():
    parser = argparse.ArgumentParser(description="VoxFlow Studio Private Supabase Worker Daemon")
    parser.add_argument("--interval", type=float, default=4.0, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Poll once and exit")
    args = parser.parse_args()
    asyncio.run(run_worker_loop(poll_interval=args.interval, once=args.once))


if __name__ == "__main__":
    main()
