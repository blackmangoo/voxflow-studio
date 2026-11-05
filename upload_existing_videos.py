"""
upload_existing_videos.py — One-time batch uploader for already-rendered videos.

Scans output/{channel}/{lang}/*.mp4 (excluding temp/), uploads each to:
    DRIVE_ROOT_FOLDER_ID/{channel}/{YYYY-MM-DD}_{concept}_{lang}/
        video.mp4
        thumbnail.jpg
        metadata.txt  (reads adjacent .txt if present, else uses filename as title)

Run:
    python upload_existing_videos.py
    python upload_existing_videos.py --dry-run   # prints what would upload without touching Drive
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_DIR = ROOT_DIR / "output"
CHANNELS = ["body_simulator", "xray_mechanics", "crazy_characters", "health_coach", "garage_guru", "code_classroom"]


def _read_metadata_file(txt_path: Path) -> dict:
    """Parses the .txt sidecar written by multi_channel_agent for title/caption/hashtags."""
    meta = {"title": "", "caption": "", "hashtags": []}
    if not txt_path.exists():
        return meta
    section = None
    lines = txt_path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if line.strip() == "TITLE:":
            section = "title"; continue
        if line.strip() == "CAPTION:":
            section = "caption"; continue
        if line.strip() == "HASHTAGS:":
            section = "hashtags"; continue
        if line.strip() == "DIALOGUE SCRIPT:":
            section = None; continue
        if section == "title" and not meta["title"]:
            meta["title"] = line.strip()
        elif section == "caption" and not meta["caption"]:
            meta["caption"] = line.strip()
        elif section == "hashtags" and line.strip():
            meta["hashtags"] = line.strip().split()
            section = None
    return meta


def _concept_from_filename(filename: str, lang: str) -> str:
    """
    Extracts concept slug from the filename pattern:
        {channel}_{lang}_{concept}_{timestamp}.mp4
    Returns the concept part in human-readable form.
    """
    # strip channel prefix and language
    name = Path(filename).stem
    # pattern: channel_lang_concept_timestamp
    # remove trailing _timestamp (all digits)
    name = re.sub(r"_\d+$", "", name)
    # remove leading channel_lang
    for channel in CHANNELS:
        prefix = f"{channel}_{lang}_"
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", " ").strip()


def discover_videos() -> list[dict]:
    """
    Finds all finished videos in output/{channel}/{lang}/*.mp4
    Returns list of dicts with channel, lang, path, concept, title, caption, hashtags.
    """
    videos = []
    for channel in CHANNELS:
        for lang in ["english", "urdu"]:
            lang_dir = OUTPUT_DIR / channel / lang
            if not lang_dir.exists():
                continue
            for mp4 in sorted(lang_dir.glob("*.mp4")):
                concept = _concept_from_filename(mp4.name, lang)
                txt_path = mp4.with_suffix(".txt")
                meta = _read_metadata_file(txt_path)
                title = meta["title"] or concept.title()
                caption = meta["caption"] or f"{concept.title()} — watch till the end!"
                hashtags = meta["hashtags"] or [f"#{channel}", f"#{lang}", "#viral", "#shorts"]
                videos.append({
                    "channel": channel,
                    "lang": lang,
                    "path": mp4,
                    "concept": concept,
                    "title": title,
                    "caption": caption,
                    "hashtags": hashtags,
                })
    return videos


def main():
    parser = argparse.ArgumentParser(description="Batch-upload existing rendered videos to Google Drive")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be uploaded without touching Drive")
    args = parser.parse_args()

    videos = discover_videos()
    if not videos:
        print("No finished videos found in output/*/english/ or output/*/urdu/")
        return

    print(f"\nFound {len(videos)} finished video(s) to upload:\n")
    for v in videos:
        size_mb = v["path"].stat().st_size // 1_000_000
        print(f"  [{v['channel']} / {v['lang']}]  {v['path'].name}  ({size_mb} MB)")
        print(f"    Title:   {v['title']}")
        print(f"    Concept: {v['concept']}")
        print()

    if args.dry_run:
        print("[DRY RUN] No uploads performed.")
        return

    from drive_uploader import upload_video_package

    results = []
    for i, v in enumerate(videos, 1):
        print(f"\n{'='*60}")
        print(f"Uploading {i}/{len(videos)}: {v['path'].name}")
        print(f"{'='*60}")
        try:
            result = upload_video_package(
                channel=v["channel"],
                concept=v["concept"],
                video_path=v["path"],
                title=v["title"],
                caption=v["caption"],
                hashtags=v["hashtags"],
                lang=v["lang"],
            )
            results.append({"video": v["path"].name, "url": result["folder_url"], "status": "OK"})
            print(f"\n  Drive folder: {result['folder_url']}")
        except Exception as e:
            results.append({"video": v["path"].name, "url": "", "status": f"FAILED: {e}"})
            print(f"\n  FAILED: {e}")

    print(f"\n{'='*60}")
    print(f"BATCH UPLOAD SUMMARY ({len(results)} videos)")
    print(f"{'='*60}")
    for r in results:
        status_icon = "✅" if r["status"] == "OK" else "❌"
        print(f"  {status_icon}  {r['video']}")
        if r["url"]:
            print(f"       {r['url']}")
        else:
            print(f"       {r['status']}")
    print()


if __name__ == "__main__":
    main()
