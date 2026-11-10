import asyncio
import json
import os
import subprocess
import sys
import threading
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
_STATUS_FILE_LOCK = threading.Lock()


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
        existing_profiles = [acc for acc in configured if (PROFILES_DIR / acc).exists()]
        self.available_accounts = [
            acc for acc in existing_profiles
            if not self.status.get(acc, {}).get("exhausted", False)
            and int(self.status.get(acc, {}).get("tokens_remaining", 1000)) > 0
        ]

        if not self.available_accounts:
            recoverable = [
                acc for acc in existing_profiles
                if int(self.status.get(acc, {}).get("tokens_remaining", 1000 if acc not in self.status else 0)) > 0
            ]
            if recoverable:
                print("⚠️ Recovering accounts with remaining tokens (> 0) into active pool...")
                self.available_accounts = recoverable
                for acc in self.available_accounts:
                    acct = self.status.setdefault(acc, {})
                    acct["exhausted"] = False
                    acct.setdefault("tokens_remaining", 1000)
                    acct.setdefault("tokens_total", 1000)
                self._save_status()
            elif not existing_profiles and int(self.status.get("account_2", {}).get("tokens_remaining", 1000)) > 0:
                self.available_accounts = ["account_2"]
            else:
                print("⚠️ Warning: All Flow accounts are exhausted for the current billing month (tokens_remaining <= 0).")

    def _check_monthly_reset(self):
        current_month = datetime.now().strftime("%Y-%m")
        saved_month = self.status.get("_last_reset_month", "")

        if current_month != saved_month:
            print(f"🔄 New month detected ({current_month})! Auto-resetting all account credits...")
            self.status["_last_reset_month"] = current_month
            for acc in ACCOUNT_NAMES:
                existing_total = self.status.get(acc, {}).get("tokens_total", 1000)
                self.status[acc] = {
                    "tokens_remaining": existing_total,
                    "tokens_total": existing_total,
                    "exhausted": False,
                    "last_reset_at": datetime.now().isoformat(),
                }
            self._save_status()

    def _load_status_unlocked(self):
        if STATUS_FILE.exists():
            try:
                with open(STATUS_FILE, "r", encoding="utf-8") as f:
                    self.status = json.load(f)
            except Exception:
                self.status = {}
        else:
            self.status = {}

    def _save_status_unlocked(self):
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.status, f, indent=2)

    def _load_status(self):
        with _STATUS_FILE_LOCK:
            self._load_status_unlocked()

    def _save_status(self):
        with _STATUS_FILE_LOCK:
            self._save_status_unlocked()

    def deduct_tokens(self, account_name: str, cost: int = 10) -> int:
        """Deducts Flow generation tokens upon successful render and updates status ledger."""
        with _STATUS_FILE_LOCK:
            self._load_status_unlocked()
            acct = self.status.setdefault(account_name, {
                "tokens_remaining": 1000,
                "tokens_total": 1000,
                "exhausted": False,
            })
            current = acct.get("tokens_remaining", 1000)
            new_val = max(0, current - cost)
            acct["tokens_remaining"] = new_val
            acct["tokens_total"] = acct.get("tokens_total", 1000)
            acct["last_rendered_at"] = datetime.now().isoformat()
            if new_val <= 0:
                acct["exhausted"] = True
                if account_name in self.available_accounts:
                    self.available_accounts.remove(account_name)
            self._save_status_unlocked()
            return new_val

    def set_account_tokens(self, account_name: str, tokens_remaining: int, tokens_total: int = 1000):
        """Directly calibrate an account's Flow token balance."""
        with _STATUS_FILE_LOCK:
            self._load_status_unlocked()
            acct = self.status.setdefault(account_name, {})
            acct["tokens_remaining"] = max(0, int(tokens_remaining))
            acct["tokens_total"] = max(1, int(tokens_total))
            acct["exhausted"] = bool(tokens_remaining <= 0)
            acct["last_synced_at"] = datetime.now().isoformat()
            self._save_status_unlocked()

    def mark_account_exhausted(self, account_name: str):
        """Marks an account as out of credits for the month."""
        print(f"\n⚠️ [{account_name.upper()}] Credits exhausted! Removing from active pool...")
        with _STATUS_FILE_LOCK:
            self._load_status_unlocked()
            if account_name not in self.status:
                self.status[account_name] = {}
            self.status[account_name]["exhausted"] = True
            self.status[account_name]["tokens_remaining"] = 0
            self.status[account_name]["tokens_total"] = self.status[account_name].get("tokens_total", 1000)
            self.status[account_name]["last_exhausted_at"] = datetime.now().isoformat()
            self._save_status_unlocked()
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
                        self.deduct_tokens(retry_acc, cost=10)
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
            self.deduct_tokens(acc_name, cost=10)
            return out_path
        except Exception as e:
            err_text = str(e).lower()
            if "exhausted" in err_text or "credit" in err_text or "not enough" in err_text:
                self.mark_account_exhausted(acc_name)
            raise e


if __name__ == "__main__":
    manager = FlowPoolManager()
    print("Available accounts in pool:", manager.available_accounts)
