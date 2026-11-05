import asyncio
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright, Page, BrowserContext
from config import PROFILES_DIR, GOOGLE_FLOW_URL, TEMP_DIR


def _kill_orphaned_chrome_for_profile(account_name: str) -> None:
    """
    Called ONLY while holding the exclusive cross-process `account_name.lock`.
    If any orphaned `chrome.exe` process is still holding `--user-data-dir=.../account_name`
    from a previously interrupted (Ctrl+C) run, terminates only that specific process tree
    so `launch_persistent_context` never fails with `TargetClosedError`.
    """
    if sys.platform != "win32":
        return
    try:
        ps_cmd = (
            f"Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
            f"Where-Object {{ $_.CommandLine -match 'browser_profiles[\\\\/]{account_name}(\"|\\s|$)' }} | "
            f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
    except Exception:
        pass


@contextlib.asynccontextmanager
async def acquire_profile_lock(account_name: str, timeout: float = 600.0):
    """
    Cross-process OS file lock for a Chrome user_data_dir profile.
    Prevents `TargetClosedError` when multiple terminals run concurrently by
    queuing access to each Chrome profile directory across processes.
    """
    lock_path = PROFILES_DIR / f"{account_name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    f = open(lock_path, "a+b")
    locked = False
    waited_logged = False
    try:
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except (OSError, IOError):
                if not waited_logged:
                    print(f"    🔒 [{account_name.upper()}] Profile currently in use by another terminal — waiting for lock...")
                    waited_logged = True
                if (time.time() - start) > timeout:
                    raise TimeoutError(f"Timed out waiting {timeout}s for profile lock on {account_name}")
                await asyncio.sleep(3.0)
        _kill_orphaned_chrome_for_profile(account_name)
        yield
    finally:
        if locked:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        try:
            f.close()
        except Exception:
            pass


def try_acquire_profile_nonblocking(account_name: str) -> bool:
    """Checks if a profile lock is currently free without blocking."""
    lock_path = PROFILES_DIR / f"{account_name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(lock_path, "a+b") as f:
            if sys.platform == "win32":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return True
    except (OSError, IOError):
        return False


class FlowWorker:
    """
    Automated worker for Google Flow (Omni 1.1 Flash Video):
    - Acquires exclusive cross-process lock on Chrome user_data_dir
    - Navigates to flow.google.com project studio (auto-switches to /u/1/ if /u/0/ is on /about)
    - Sets mode to Omni Video (9:16 vertical, 10s)
    - Submits cinematic prompt into ProseMirror editor (ignoring hidden g-recaptcha-response)
    - Monitors generation progress until 100%
    - Downloads MP4 via Playwright's native browser download / request stack with SSL retry fallback
    """

    def __init__(self, account_name: str = "account_1"):
        self.account_name = account_name
        self.profile_dir = PROFILES_DIR / account_name

    async def _safe_screenshot(self, page: Page, name: str) -> None:
        """Non-blocking diagnostic screenshot that never crashes a render."""
        try:
            shot_path = TEMP_DIR / f"debug_{self.account_name}_{name}.png"
            await page.screenshot(path=str(shot_path), timeout=5000, animations="disabled")
        except Exception:
            pass

    def _download_with_retries(self, url: str, output_path: Path) -> bool:
        """Downloads video from CDN URL using retry-hardened requests session."""
        session = requests.Session()
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        for attempt in range(1, 5):
            try:
                resp = session.get(url, stream=True, timeout=60)
                if resp.status_code == 200:
                    with open(output_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                    if output_path.exists() and output_path.stat().st_size > 100_000:
                        return True
            except Exception as e:
                print(f"[{self.account_name.upper()}] CDN download attempt {attempt}/4 warning: {e}")
                time.sleep(2 * attempt)
        return False

    async def generate_clip(
        self,
        prompt: str,
        output_filename: str,
        timeout_seconds: int = 240,
        headless: bool = False,
        aspect_ratio: str = "9:16",
        duration: str = "10s"
    ) -> Path:
        output_path = Path(output_filename)
        if not output_path.is_absolute():
            output_path = TEMP_DIR / output_filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.profile_dir.exists():
            raise FileNotFoundError(f"Profile directory not found: {self.profile_dir}")

        async with acquire_profile_lock(self.account_name):
            print(f"[{self.account_name.upper()}] Opening studio for: {prompt[:50]}...")

            video_cdn_url = None
            downloaded_directly = False

            async with async_playwright() as p:
                context: BrowserContext = await p.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    channel="chrome",
                    headless=headless,
                    accept_downloads=True,
                    viewport={"width": 1280, "height": 800},
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
                )

                try:
                    page: Page = context.pages[0] if context.pages else await context.new_page()

                    # Listen for the CDN signed video URL response
                    def on_response(res):
                        nonlocal video_cdn_url
                        if "flow-content.google/video/" in res.url and res.status in (200, 206):
                            video_cdn_url = res.url

                    page.on("response", on_response)

                    # 1. Navigate to Google Flow
                    await page.goto(GOOGLE_FLOW_URL, wait_until="domcontentloaded", timeout=45000)
                    await page.wait_for_timeout(3000)

                    # Auto-handle /about redirect when active Gmail account is on /u/1/
                    if "/about" in page.url:
                        print(f"[{self.account_name.upper()}] Redirected to /about on /u/0 — switching to /u/1/ active session...")
                        await page.goto("https://flow.google.com/u/1/?pli=1", wait_until="domcontentloaded", timeout=45000)
                        await page.wait_for_timeout(3500)

                    if "/about" in page.url:
                        # Fallback via AccountChooser selecting the profile's logged-in email
                        target_email = ""
                        try:
                            prefs_path = self.profile_dir / "Default" / "Preferences"
                            if prefs_path.exists():
                                pdata = json.loads(prefs_path.read_text(encoding="utf-8", errors="ignore"))
                                target_email = (pdata.get("account_info") or [{}])[0].get("email", "")
                        except Exception:
                            pass
                        print(f"[{self.account_name.upper()}] Resolving active account ({target_email or 'default'}) via AccountChooser...")
                        await page.goto(
                            "https://accounts.google.com/AccountChooser?continue=https://flow.google.com/",
                            wait_until="domcontentloaded",
                            timeout=30000
                        )
                        await page.wait_for_timeout(2500)
                        acct_item = (
                            page.locator(f"text='{target_email}'").first
                            if target_email
                            else page.locator("div[data-email], text=@gmail.com").first
                        )
                        if await acct_item.is_visible():
                            await acct_item.click(force=True)
                            await page.wait_for_timeout(4000)

                    # 2. Enter project studio if not already inside one
                    if "/project/" not in page.url:
                        await page.wait_for_timeout(2500)

                        new_proj_card = page.locator(
                            "button:has-text('New project'), div:has-text('New project'), [aria-label*='New project']"
                        ).first
                        start_btn = page.locator("text=Start Creating").first
                        existing_proj = page.locator("a[href*='/project/'], div[class*='project-card']").first

                        if await new_proj_card.is_visible():
                            print(f"[{self.account_name.upper()}] Opening via '+ New project' card...")
                            await new_proj_card.click(force=True)
                        elif await start_btn.is_visible():
                            print(f"[{self.account_name.upper()}] Opening via 'Start Creating'...")
                            await start_btn.click(force=True)
                        elif await existing_proj.is_visible():
                            print(f"[{self.account_name.upper()}] Opening existing project...")
                            await existing_proj.click(force=True)
                        else:
                            await page.mouse.click(500, 700)

                    # 3. Wait for the Studio UI prompt editor (explicitly excluding hidden g-recaptcha-response)
                    prompt_input = page.locator(
                        "div.ProseMirror[contenteditable='true'], "
                        "div[contenteditable='true'], "
                        "textarea:not([name*='recaptcha']):not([class*='recaptcha'])"
                    ).first

                    try:
                        await prompt_input.wait_for(state="visible", timeout=45000)
                    except Exception:
                        print(f"[{self.account_name.upper()}] Prompt input not yet visible — clicking project card fallback...")
                        new_proj_retry = page.locator("button:has-text('New project'), div:has-text('New project')").first
                        if await new_proj_retry.is_visible():
                            await new_proj_retry.click(force=True)
                        else:
                            await page.mouse.click(500, 700)
                        await page.wait_for_timeout(3000)
                        await prompt_input.wait_for(state="visible", timeout=15000)

                    await page.wait_for_timeout(1500)

                    # 4. Lock in Video mode & 9:16 aspect ratio in model pill
                    pill = page.locator("button:has-text('Video'), button:has-text('Nano Banana'), div[class*='pill']").last
                    if await pill.is_visible():
                        await pill.click(force=True)
                        await page.wait_for_timeout(800)

                        video_toggle = page.locator(".cdk-overlay-container button:has-text('Video')").first
                        if await video_toggle.is_visible():
                            await video_toggle.click(force=True)
                            await page.wait_for_timeout(500)

                        ratio_btn = page.locator(f".cdk-overlay-container button:has-text('{aspect_ratio}')").first
                        if await ratio_btn.is_visible():
                            await ratio_btn.click(force=True)
                            await page.wait_for_timeout(500)

                        dur_btn = page.locator(f".cdk-overlay-container button:has-text('{duration}')").first
                        if await dur_btn.is_visible():
                            await dur_btn.click(force=True)
                            await page.wait_for_timeout(500)

                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(400)
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(600)

                    # Record existing video tiles before generating
                    existing_labels = set()
                    try:
                        for el in await page.locator("flow-grid-tile-container:has(flow-video-tile)").all():
                            aria = await el.get_attribute("aria-label") or ""
                            if aria:
                                existing_labels.add(aria.lower().strip())
                    except Exception:
                        pass

                    # 5. Input prompt into creation bar
                    await prompt_input.click(force=True)
                    await page.wait_for_timeout(400)
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await page.keyboard.insert_text(prompt)
                    await page.wait_for_timeout(800)

                    # 6. Submit generation
                    arrow_btn = page.locator("button:has-text('arrow_forward'), button:has(span:has-text('arrow_forward'))").last
                    print(f"[{self.account_name.upper()}] Submitting prompt to Omni 1.1 Flash...")

                    await prompt_input.focus()
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(1000)

                    if await arrow_btn.is_visible():
                        is_disabled = await arrow_btn.get_attribute("disabled")
                        if not is_disabled:
                            await arrow_btn.click(force=True)

                    await page.wait_for_timeout(2500)

                    # Check for policy violation or credit exhaustion right after submit
                    body_low = (await page.locator("body").inner_text()).lower()
                    if "not enough credits" in body_low or "insufficient credits" in body_low or "out of credits" in body_low:
                        raise RuntimeError(f"[{self.account_name.upper()}] Credits exhausted on this account.")

                    # 7. Monitor progress until percentage completes
                    print(f"[{self.account_name.upper()}] Waiting for Omni Flash render...")
                    percent_loc = page.locator("text=%").first

                    progress_started = False
                    for _ in range(18):  # up to 36s for % to appear
                        if await percent_loc.is_visible():
                            progress_started = True
                            break

                        always_approve = page.locator("text='Always approve'").first
                        approve = page.locator("text='Approve'").first

                        if await always_approve.is_visible():
                            print(f"[{self.account_name.upper()}] Credit confirmation detected. Clicking 'Always approve'...")
                            await always_approve.click(force=True)
                            await page.wait_for_timeout(2000)
                        elif await approve.is_visible():
                            print(f"[{self.account_name.upper()}] Credit confirmation detected. Clicking 'Approve'...")
                            await approve.click(force=True)
                            await page.wait_for_timeout(2000)

                        # Also check if credit exhaustion message popped up
                        credit_err = page.locator("text=/not enough credits|out of credits|insufficient credits/i").first
                        if await credit_err.is_visible():
                            raise RuntimeError(f"[{self.account_name.upper()}] Credits exhausted on this account.")

                        await page.wait_for_timeout(2000)

                    if not progress_started:
                        print(f"[{self.account_name.upper()}] % indicator didn't appear. Forcing retry...")
                        await prompt_input.click(force=True)
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(1000)
                        if await arrow_btn.is_visible():
                            await arrow_btn.click(force=True)
                        try:
                            await percent_loc.wait_for(state="visible", timeout=15000)
                        except Exception:
                            print(f"[{self.account_name.upper()}] Proceeding to check for video tile...")

                    start_time = time.time()
                    while (time.time() - start_time) < timeout_seconds:
                        if await percent_loc.is_visible():
                            try:
                                txt = await percent_loc.inner_text(timeout=2000)
                                print(f"[{self.account_name.upper()}] Progress: {txt}")
                            except Exception:
                                print(f"[{self.account_name.upper()}] Render completed!")
                                break
                            await page.wait_for_timeout(4000)
                        else:
                            print(f"[{self.account_name.upper()}] Render completed!")
                            break

                    await page.wait_for_timeout(5000)

                    # 8. Locate the new video tile
                    video_tiles = await page.locator("flow-grid-tile-container:has(flow-video-tile)").all()
                    target_tile = None
                    for vt in video_tiles:
                        aria = (await vt.get_attribute("aria-label") or "").lower().strip()
                        if aria and aria not in existing_labels:
                            target_tile = vt
                            print(f"[{self.account_name.upper()}] Identified new video tile: '{aria}'")
                            break

                    if not target_tile and video_tiles:
                        target_tile = video_tiles[0]

                    if not target_tile:
                        await self._safe_screenshot(page, "no_tile_error")
                        raise RuntimeError(f"[{self.account_name.upper()}] No video tile found on canvas after generation.")

                    print(f"[{self.account_name.upper()}] Opening video card...")
                    await target_tile.click(force=True)
                    await page.wait_for_timeout(3500)

                    # 9. Wait for Download button to become enabled
                    dl_btn = page.locator("button[aria-label*='Download media'], button[aria-label*='Download']").first
                    print(f"[{self.account_name.upper()}] Waiting for video encoding to finish...")

                    for _ in range(45):
                        if video_cdn_url:
                            break
                        if await dl_btn.is_visible():
                            is_disabled = await dl_btn.get_attribute("disabled")
                            classes = await dl_btn.get_attribute("class") or ""
                            if not is_disabled and "mat-mdc-button-disabled" not in classes:
                                break
                        await page.wait_for_timeout(1000)

                    # 10. Download directly inside Playwright context first (prevents SSLEOFError & stray Downloads files)
                    if video_cdn_url:
                        try:
                            print(f"[{self.account_name.upper()}] Fetching MP4 via browser network context...")
                            api_resp = await context.request.get(video_cdn_url, timeout=60000)
                            if api_resp.ok:
                                body_bytes = await api_resp.body()
                                if len(body_bytes) > 100_000:
                                    with open(output_path, "wb") as f:
                                        f.write(body_bytes)
                                    downloaded_directly = True
                        except Exception as e:
                            print(f"[{self.account_name.upper()}] Browser context fetch fallback: {e}")

                    # If not downloaded yet, click the UI download menu and capture via Playwright expect_download
                    if not downloaded_directly:
                        print(f"[{self.account_name.upper()}] Triggering download menu with Playwright capture...")
                        try:
                            await dl_btn.click(force=True, timeout=10000)
                            await page.wait_for_timeout(1000)
                            opt_720 = page.locator(
                                ".cdk-overlay-container button:has-text('720p'), "
                                ".cdk-overlay-container button:has-text('Original size')"
                            ).first
                            if await opt_720.is_visible():
                                async with page.expect_download(timeout=45000) as dl_info:
                                    await opt_720.click(force=True, timeout=10000)
                                download = await dl_info.value
                                await download.save_as(str(output_path))
                                if output_path.exists() and output_path.stat().st_size > 100_000:
                                    downloaded_directly = True
                        except Exception as e:
                            print(f"[{self.account_name.upper()}] Download menu capture note: {e}")
                            # If video_cdn_url was captured during the click, try context.request.get
                            if video_cdn_url and not downloaded_directly:
                                try:
                                    api_resp = await context.request.get(video_cdn_url, timeout=60000)
                                    if api_resp.ok:
                                        body_bytes = await api_resp.body()
                                        if len(body_bytes) > 100_000:
                                            with open(output_path, "wb") as f:
                                                f.write(body_bytes)
                                            downloaded_directly = True
                                except Exception:
                                    pass
                finally:
                    try:
                        await context.close()
                    except Exception:
                        pass

            # 11. Final fallback: retry-hardened requests.Session outside browser
            if not downloaded_directly:
                if not video_cdn_url:
                    raise RuntimeError(f"[{self.account_name.upper()}] Failed to intercept signed video CDN URL.")
                print(f"[{self.account_name.upper()}] Downloading MP4 from Google Cloud CDN (with SSL retry)...")
                ok = self._download_with_retries(video_cdn_url, output_path)
                if not ok:
                    raise RuntimeError(f"[{self.account_name.upper()}] Failed to download video from CDN after retries.")

            print(f"[{self.account_name.upper()}] ✅ Video downloaded successfully: {output_path} ({output_path.stat().st_size} bytes)")
            return output_path


if __name__ == "__main__":
    worker = FlowWorker("account_2")
    prompt = "Cinematic slow push-in shot of glowing neon hourglass in dark room, turquoise and magenta light beams, 8k vertical video"
    asyncio.run(worker.generate_clip(prompt, "test_flow_worker.mp4", timeout_seconds=120, headless=False))
