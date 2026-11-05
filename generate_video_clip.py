import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from video_engine.flow_worker import FlowWorker
from video_engine.pool_manager import FlowPoolManager

def optimize_for_web_background(input_path: Path, output_path: Path) -> Path:
    """
    Optimizes MP4 specifically for website video backgrounds:
    - Strips audio tracks (-an) to save bandwidth and ensure autoplay compliance.
    - Sets pix_fmt yuv420p for 100% browser compatibility (Safari, Chrome, Firefox).
    - Injects +faststart flag so video streams and plays instantly before full download.
    - Applies optimal H.264 compression (crf 22) for high visual quality at minimal file size.
    """
    temp_optimized = output_path.parent / f"web_opt_{output_path.name}"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-an",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(temp_optimized)
    ]
    try:
        print("\n⚙️ Optimizing video for website background (faststart + compression)...")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if temp_optimized.exists() and temp_optimized.stat().st_size > 0:
            if output_path.exists():
                output_path.unlink()
            temp_optimized.rename(output_path)
            orig_size = input_path.stat().st_size / (1024 * 1024)
            opt_size = output_path.stat().st_size / (1024 * 1024)
            print(f"✅ Web optimization complete: {orig_size:.2f}MB -> {opt_size:.2f}MB")
            return output_path
    except Exception as e:
        print(f"⚠️ Web optimization warning: {e}. Keeping raw download.")
    return input_path

async def generate_single_video(
    prompt: str,
    output_path: str,
    aspect_ratio: str = "16:9",
    duration: str = "10s",
    account: str = None,
    optimize_web: bool = True
) -> Path:
    target_output = Path(output_path).resolve()
    target_output.parent.mkdir(parents=True, exist_ok=True)

    # Account selection
    if not account:
        pool = FlowPoolManager()
        if not pool.available_accounts:
            raise RuntimeError("No available Google Flow accounts found with active credits.")
        # Pick the first available account from pool
        account = pool.available_accounts[0]

    print("=" * 70)
    print(" 🎬 GOOGLE FLOW STANDALONE VIDEO GENERATOR")
    print("=" * 70)
    print(f" Account:      {account.upper()}")
    print(f" Aspect Ratio: {aspect_ratio} ({'Landscape / Web Hero' if aspect_ratio == '16:9' else 'Vertical'})")
    print(f" Duration:     {duration}")
    print(f" Output Target: {target_output}")
    print(f" Prompt:       {prompt}")
    print("=" * 70 + "\n")

    worker = FlowWorker(account_name=account)
    raw_video = await worker.generate_clip(
        prompt=prompt,
        output_filename=str(target_output),
        timeout_seconds=240,
        headless=False,
        aspect_ratio=aspect_ratio,
        duration=duration
    )

    if optimize_web:
        optimize_for_web_background(raw_video, target_output)

    print("\n" + "=" * 70)
    print(f" 🎉 VIDEO READY: {target_output}")
    print(f" File Size:   {target_output.stat().st_size / (1024 * 1024):.2f} MB")
    print("=" * 70 + "\n")
    return target_output

def main():
    parser = argparse.ArgumentParser(description="Generate standalone 10s Omni 1.1 Flash video for websites or other projects")
    parser.add_argument("--prompt", type=str, required=True, help="Video generation prompt for Omni Flash")
    parser.add_argument("--output", type=str, required=True, help="Absolute or relative destination path for MP4")
    parser.add_argument("--aspect", type=str, default="16:9", choices=["16:9", "9:16", "1:1"], help="Aspect ratio (default: 16:9 for websites)")
    parser.add_argument("--duration", type=str, default="10s", choices=["10s", "5s"], help="Clip duration (default: 10s)")
    parser.add_argument("--account", type=str, default=None, help="Specific account name e.g. account_5 (default: auto from pool)")
    parser.add_argument("--no-optimize", action="store_true", help="Skip web faststart and compression optimization")
    args = parser.parse_args()

    asyncio.run(generate_single_video(
        prompt=args.prompt,
        output_path=args.output,
        aspect_ratio=args.aspect,
        duration=args.duration,
        account=args.account,
        optimize_web=not args.no_optimize
    ))

if __name__ == "__main__":
    main()
