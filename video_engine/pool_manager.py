import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import ACCOUNT_NAMES, TEMP_DIR, PROFILES_DIR
from video_engine.flow_worker import FlowWorker, try_acquire_profile_nonblocking

STATUS_FILE = Path(__file__).parent / "account_credit_status.json"


class FlowPoolManager:
    """
    Manages the Google AI Pro accounts:
    - Uses ACTIVE_ACCOUNTS (account_2, account_3, account_4 prioritized before account_1).
    - Tracks credit exhaustion.
    - Automatically retries any failed scene on remaining active accounts instead of aborting.
    - Scopes output clip filenames by channel & PID to prevent multi-terminal collisions.
    """

    def __init__(self, accounts: List[str] = None):
        self._load_status()
        self._check_monthly_reset()

        configured = accounts or ACCOUNT_NAMES
        self.available_accounts = [
            acc for acc in configured
            if (PROFILES_DIR / acc).exists() and not self.status.get(acc, {}).get("exhausted", False)
        ]

        if not self.available_accounts:
            print("⚠️ All accounts marked exhausted or uninitialized. Resetting pool status...")
            self.available_accounts = [acc for acc in configured if (PROFILES_DIR / acc).exists()]
            for acc in self.available_accounts:
                self.status[acc] = {"exhausted": False}
            self._save_status()

        if not self.available_accounts:
            self.available_accounts = ["account_2"]

    def _check_monthly_reset(self):
        current_month = datetime.now().strftime("%Y-%m")
        saved_month = self.status.get("_last_reset_month", "")

        if current_month != saved_month:
            print(f"🔄 New month detected ({current_month})! Auto-resetting all account credits...")
            self.status = {"_last_reset_month": current_month}
            self._save_status()

    def _load_status(self):
        if STATUS_FILE.exists():
            try:
                with open(STATUS_FILE, "r", encoding="utf-8") as f:
                    self.status = json.load(f)
            except Exception:
                self.status = {}
        else:
            self.status = {}

    def _save_status(self):
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.status, f, indent=2)

    def mark_account_exhausted(self, account_name: str):
        """Marks an account as out of credits for the month."""
        print(f"\n⚠️ [{account_name.upper()}] Credits exhausted! Removing from active pool...")
        if account_name not in self.status:
            self.status[account_name] = {}
        self.status[account_name]["exhausted"] = True
        self._save_status()
        if account_name in self.available_accounts:
            self.available_accounts.remove(account_name)

    async def generate_mock_clip(self, scene_idx: int, output_path: Path) -> Path:
        print(f"[SIMULATION] Rendering 10s mock clip for Scene {scene_idx + 1}...")
        colors = ["testsrc", "smptebars", "mandelbrot"]
        pattern = colors[scene_idx % len(colors)]
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"{pattern}=size=1080x1920:rate=30",
            "-t", "10",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            str(output_path)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_path

    async def render_scenes_parallel(
        self,
        scene_prompts: List[str],
        mock_mode: bool = False,
        channel: str = "episode",
    ) -> List[str]:
        run_tag = f"{channel}_{os.getpid()}"
        if mock_mode:
            print("    [MOCK MODE] Simulating parallel renders...")
            tasks = []
            clip_paths = []
            for idx, _ in enumerate(scene_prompts):
                clip_file = TEMP_DIR / f"raw_{run_tag}_scene_{idx + 1}.mp4"
                clip_paths.append(str(clip_file))
                tasks.append(self.generate_mock_clip(idx, clip_file))
            await asyncio.gather(*tasks)
            return clip_paths

        if not self.available_accounts:
            raise RuntimeError("No available Flow accounts left! All are exhausted.")

        # Order accounts so currently unlocked profiles come first (maintaining priority order)
        free_now = [a for a in self.available_accounts if try_acquire_profile_nonblocking(a)]
        busy_now = [a for a in self.available_accounts if a not in free_now]
        ordered_pool = free_now + busy_now

        print(f"\n🚀 Launching {len(scene_prompts)} parallel renders across active accounts: {ordered_pool}")

        tasks = []
        out_paths = []
        assigned_accounts = []
        for idx, prompt in enumerate(scene_prompts):
            acc_name = ordered_pool[idx % len(ordered_pool)]
            assigned_accounts.append(acc_name)
            clip_file = TEMP_DIR / f"raw_{run_tag}_scene_{idx + 1}.mp4"
            out_paths.append(str(clip_file))
            worker = FlowWorker(acc_name)
            tasks.append(self._render_single_scene(worker, acc_name, prompt, clip_file, idx + 1))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Automatic failover for any scene that failed on its initial account
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                failed_acc = assigned_accounts[i]
                last_err_detail = f"{type(res).__name__}: {res}" if str(res) else type(res).__name__
                print(f"    ⚠️ Scene {i + 1} failed on [{failed_acc.upper()}]: {last_err_detail}")
                clip_file = Path(out_paths[i])
                prompt = scene_prompts[i]

                # Build fallback candidate list (prefer accounts other than the one that just failed)
                fallback_Order = [a for a in self.available_accounts if a != failed_acc]
                if failed_acc in self.available_accounts:
                    fallback_Order.append(failed_acc)

                recovered = False
                for retry_acc in fallback_Order:
                    print(f"    🔄 Retrying Scene {i + 1} on backup account [{retry_acc.upper()}]...")
                    try:
                        retry_worker = FlowWorker(retry_acc)
                        await retry_worker.generate_clip(prompt, str(clip_file), 240, headless=False)
                        print(f"    ✅ [{retry_acc.upper()}] Successfully recovered Scene {i + 1}!")
                        recovered = True
                        break
                    except Exception as retry_err:
                        err_text = str(retry_err).lower()
                        last_err_detail = f"{type(retry_err).__name__}: {retry_err}" if str(retry_err) else type(retry_err).__name__
                        if "exhausted" in err_text or "credit" in err_text or "not enough" in err_text:
                            self.mark_account_exhausted(retry_acc)
                        print(f"    ❌ Backup attempt on [{retry_acc.upper()}] failed: {last_err_detail}")

                if not recovered:
                    raise RuntimeError(f"Scene {i + 1} failed across all tried accounts. Last error: {last_err_detail}")

        print("✅ All parallel video scenes rendered successfully!\n")
        return out_paths

    async def _render_single_scene(
        self,
        worker: FlowWorker,
        acc_name: str,
        prompt: str,
        out_path: Path,
        scene_num: int
    ) -> Path:
        delay = (scene_num - 1) * 8  # Stagger launches: 0s, 8s, 16s, 24s
        if delay > 0:
            print(f"    ⏳ [{acc_name.upper()}] Staggering launch by {delay}s to stabilize Chrome...")
            await asyncio.sleep(delay)

        print(f"    🎬 [{acc_name.upper()}] Starting render for Scene {scene_num}...")
        try:
            await worker.generate_clip(prompt, str(out_path), 240, headless=False)
            print(f"    ✅ [{acc_name.upper()}] Finished Scene {scene_num}.")
            return out_path
        except Exception as e:
            err_text = str(e).lower()
            if "exhausted" in err_text or "credit" in err_text or "not enough" in err_text:
                self.mark_account_exhausted(acc_name)
            raise e


if __name__ == "__main__":
    manager = FlowPoolManager()
    print("Available accounts in pool:", manager.available_accounts)
