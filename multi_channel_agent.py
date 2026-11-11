import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import TEMP_DIR
from brain.multi_channel_director import MultiChannelDirector
from voice.voxstudio_engine import VoxStudioEngine
from compositor.modern_subtitles import ModernSubtitleGenerator
from compositor.video_editor import VideoCompositor
from video_engine.pool_manager import FlowPoolManager
from video_engine.asset_fetcher import get_random_audio, ensure_channel_assets
from video_engine.clip_quality_scorer import score_and_filter_clips
from notifications import notify_all
from drive_uploader import upload_video_package

NICHE_NAMES = {
    "body_simulator":  "body_simulator",
    "xray_mechanics":  "xray_mechanics",
    "crazy_characters":"crazy_characters",
    "health_coach":    "health_coach",
    "garage_guru":     "garage_guru",
    "code_classroom":  "code_classroom",
}

def get_channel_dirs(channel: str):
    base = ROOT_DIR / "output" / channel
    urdu_dir = base / "urdu"
    english_dir = base / "english"
    urdu_dir.mkdir(parents=True, exist_ok=True)
    english_dir.mkdir(parents=True, exist_ok=True)
    return urdu_dir, english_dir

async def produce_dual_language_episode(
    channel: str = "body_simulator",
    mock_video: bool = False,
    max_scenes: int = None,
    target_lang: str = "english",
    custom_prompt: str = None,
    visual_style: str = None,
    custom_scenes: list = None,
    progress_callback=None,
    wa_token: str = None,
    wa_user_id: str = None,
    allow_owner_wa_fallback: bool = True,
):
    print("\n" + "=" * 80)
    print(f" 🎬 AUTONOMOUS PIPELINE: [{channel.upper()}] | LANG: {target_lang.upper()}")
    print("=" * 80)
    urdu_dir, english_dir = get_channel_dirs(channel)
    print(f"Video Mode:      {'Simulation (Mock Clips)' if mock_video else 'Google Flow (Omni 1.1 Flash 10s)'}")
    print("=" * 80 + "\n")

    start_time = time.time()

    # Guarantee CC0 BGM + SFX are populated before compositing begins
    print(f"🎵 [0/6] ASSETS: Ensuring copyright-safe BGM for '{channel}'...")
    await asyncio.to_thread(ensure_channel_assets, channel)

    # 1. BRAIN: Autonomous Ideation, Custom Prompt Director, or Manual Scene Override
    print(f"🧠 [1/6] BRAIN: Selecting concept and generating scripts...")
    director = MultiChannelDirector()
    if custom_scenes and len(custom_scenes) > 0:
        episode = await asyncio.to_thread(
            director.compile_manual_episode,
            custom_scenes,
            custom_prompt or "Custom 3D Production",
            visual_style or "",
            channel,
        )
    elif custom_prompt and len(custom_prompt.strip()) >= 4:
        episode = await asyncio.to_thread(
            director.generate_custom_episode,
            custom_prompt,
            visual_style or "",
            channel,
        )
    else:
        episode = await asyncio.to_thread(director.generate_episode, channel)

    scene_prompts = [s.flow_prompt for s in episode.scenes]
    if max_scenes and max_scenes > 0:
        scene_prompts = scene_prompts[:max_scenes]
        episode.scenes = episode.scenes[:max_scenes]
        episode.dialogue_urdu = episode.dialogue_urdu[:max_scenes]
        episode.dialogue_english = episode.dialogue_english[:max_scenes]

    if progress_callback:
        try:
            progress_callback(
                stage=f"[2/6] Rendering {len(scene_prompts)}× 10s 3D scenes: '{episode.concept[:45]}'",
                progress=35,
                concept=episode.concept,
                script_preview={
                    "title_english": episode.title_english,
                    "title_urdu": episode.title_urdu,
                    "scenes": [s.flow_prompt for s in episode.scenes],
                    "dialogue_english": [{"speaker": d.speaker, "line": d.line} for d in episode.dialogue_english],
                    "dialogue_urdu": [{"speaker": d.speaker, "line": d.line} for d in episode.dialogue_urdu],
                },
            )
        except Exception:
            pass

    print(f"    Concept:          {episode.concept}")
    print(f"    English Title:    {episode.title_english}")
    print(f"    Scenes to Render: {len(scene_prompts)}\n")

    # 2. VIDEO ENGINE: Render Shared High-Resolution Video Clips (10s each)
    print(f"🎥 [2/6] VIDEO ENGINE: Rendering {len(scene_prompts)} scenes on Google Flow (Omni 1.1 Flash)...")
    pool = FlowPoolManager()
    clip_paths = await pool.render_scenes_parallel(scene_prompts, mock_mode=mock_video, channel=channel)

    # Quality gate: reject static/broken clips before compositing
    if progress_callback:
        try:
            progress_callback(stage="[3/6] Gemini Vision Quality Gate & Voice Synthesis...", progress=65)
        except Exception:
            pass
    gemini_key = os.environ.get("GEMINI_API_KEY")
    clip_paths = await asyncio.to_thread(score_and_filter_clips, clip_paths, gemini_key)

    bgm_folder = ROOT_DIR / "assets" / "music" / channel
    actual_bgm = get_random_audio(bgm_folder)

    vox_engine = VoxStudioEngine()
    sub_gen = ModernSubtitleGenerator()
    compositor = VideoCompositor()

    urdu_final, english_final = None, None
    safe_concept = "".join(c for c in episode.concept if c.isascii() and (c.isalnum() or c in (" ", "_"))).strip().replace(" ", "_").lower()[:30]
    if not safe_concept:
        safe_concept = "episode"
    timestamp = int(time.time())
    run_uid = f"{os.getpid()}_{timestamp}"

    # --- URDU PROCESSING ---
    if target_lang in ["urdu", "both"]:
        if progress_callback:
            try:
                progress_callback(stage="[4/6] Synthesizing Urdu Neural Character Voiceover...", progress=74)
            except Exception:
                pass
        print("\n🎙️ [VOICE URDU]: Synthesizing native character voice acting...")
        urdu_payload = [{"speaker": d.voice_persona, "line": d.line} for d in episode.dialogue_urdu]
        urdu_voice_data = await vox_engine.generate_dialogue_async(urdu_payload, lang="urdu", output_prefix=f"{episode.channel}_urdu_audio")

        if progress_callback:
            try:
                progress_callback(stage="[5/6] Burning Branded Urdu Subtitles & Sidechain Ducking...", progress=86)
            except Exception:
                pass
        print("✨ [SUBTITLES URDU]: Formatting lower-third animated captions...")
        urdu_sub_path = sub_gen.generate_ass(
            urdu_voice_data["words"],
            lang="urdu",
            output_path=TEMP_DIR / f"{episode.channel}_urdu_{run_uid}.ass",
            hook_text=getattr(episode, "hook_text_urdu", ""),
            channel=channel
        )

        print("🎞️ [COMPOSITING URDU]: Assembling final vertical release...")
        urdu_filename = f"{channel}_urdu_{safe_concept}_{timestamp}.mp4"
        urdu_final = urdu_dir / urdu_filename
        try:
            await asyncio.to_thread(
                compositor.assemble_video_synced,
                clip_paths=clip_paths,
                audio_path=urdu_voice_data["audio_path"],
                scene_durations=urdu_voice_data.get("line_durations", []),
                subtitles_path=str(urdu_sub_path),
                output_filename=str(urdu_final),
                music_path=actual_bgm,
                channel=channel,
            )
        finally:
            Path(urdu_sub_path).unlink(missing_ok=True)
            Path(urdu_voice_data["audio_path"]).unlink(missing_ok=True)
        # Save Urdu Metadata
        urdu_meta = urdu_final.with_suffix(".txt")
        with open(urdu_meta, "w", encoding="utf-8") as f:
            f.write(f"TITLE:\n{episode.title_urdu}\n\n")
            f.write(f"CAPTION:\n{episode.caption_urdu}\n\n")
            f.write(f"HASHTAGS:\n{' '.join(episode.hashtags)}\n\n")
            f.write("DIALOGUE SCRIPT:\n")
            for d in episode.dialogue_urdu:
                f.write(f"[{d.speaker.upper()}]: {d.line}\n")

    # --- ENGLISH PROCESSING ---
    if target_lang in ["english", "both"]:
        if progress_callback:
            try:
                progress_callback(stage="[4/6] Synthesizing English Neural Character Voiceover...", progress=78)
            except Exception:
                pass
        print("\n🎙️ [VOICE ENGLISH]: Synthesizing character dialogue...")
        english_payload = [{"speaker": d.voice_persona, "line": d.line} for d in episode.dialogue_english]
        english_voice_data = await vox_engine.generate_dialogue_async(english_payload, lang="english", output_prefix=f"{episode.channel}_english_audio")

        if progress_callback:
            try:
                progress_callback(stage="[5/6] Burning Branded English Subtitles & Sidechain Ducking...", progress=90)
            except Exception:
                pass
        print("✨ [SUBTITLES ENGLISH]: Formatting lower-third animated captions...")
        english_sub_path = sub_gen.generate_ass(
            english_voice_data["words"],
            lang="english",
            output_path=TEMP_DIR / f"{episode.channel}_english_{run_uid}.ass",
            hook_text=getattr(episode, "hook_text_english", ""),
            channel=channel
        )

        print("🎞️ [COMPOSITING ENGLISH]: Assembling final vertical release...")
        english_filename = f"{channel}_english_{safe_concept}_{timestamp}.mp4"
        english_final = english_dir / english_filename
        try:
            await asyncio.to_thread(
                compositor.assemble_video_synced,
                clip_paths=clip_paths,
                audio_path=english_voice_data["audio_path"],
                scene_durations=english_voice_data.get("line_durations", []),
                subtitles_path=str(english_sub_path),
                output_filename=str(english_final),
                music_path=actual_bgm,
                channel=channel,
            )
        finally:
            Path(english_sub_path).unlink(missing_ok=True)
            Path(english_voice_data["audio_path"]).unlink(missing_ok=True)
        # Save English Metadata
        english_meta = english_final.with_suffix(".txt")
        with open(english_meta, "w", encoding="utf-8") as f:
            f.write(f"TITLE:\n{episode.title_english}\n\n")
            f.write(f"CAPTION:\n{episode.caption_english}\n\n")
            f.write(f"HASHTAGS:\n{' '.join(episode.hashtags)}\n\n")
            f.write("DIALOGUE SCRIPT:\n")
            for d in episode.dialogue_english:
                f.write(f"[{d.speaker.upper()}]: {d.line}\n")

    elapsed = time.time() - start_time
    print("\n" + "=" * 80)
    print(f" 🎉 GENERATION COMPLETE! [{channel.upper()}] | {target_lang.upper()}")
    print("=" * 80)
    if urdu_final:
        print(f" 🇵🇰 URDU VIDEO:    {urdu_final}")
    if english_final:
        print(f" 🌐 ENGLISH VIDEO: {english_final}")
    print(f" Total Time:       {elapsed:.1f}s")
    print("=" * 80 + "\n")

    if not mock_video:
        # Upload all generated language packages to Google Drive (live renders only)
        drive_result = {}
        packages_to_upload = []
        if english_final:
            packages_to_upload.append((english_final, "english", episode.title_english, episode.caption_english))
        if urdu_final:
            packages_to_upload.append((urdu_final, "urdu", episode.title_urdu, episode.caption_urdu))

        for vid_path, lang_key, title_str, cap_str in packages_to_upload:
            try:
                res = await asyncio.to_thread(
                    upload_video_package,
                    channel=channel,
                    concept=episode.concept,
                    video_path=vid_path,
                    title=title_str,
                    caption=cap_str,
                    hashtags=episode.hashtags,
                    lang=lang_key,
                )
                if not drive_result:
                    drive_result = res
                print(f" Drive ({lang_key}): {res.get('folder_url', 'uploaded')}")
            except Exception as e:
                print(f" [Drive] Upload skipped/failed ({lang_key}): {e}")

        primary_final = english_final if english_final else urdu_final
        primary_lang = "english" if english_final else "urdu"
        primary_title = episode.title_english if primary_lang == "english" else episode.title_urdu

        # Send WhatsApp/Discord/Telegram with Drive link + hashtags (isolated per user!)
        await asyncio.to_thread(
            notify_all,
            title=primary_title,
            concept=episode.concept,
            channel=channel,
            video_path=str(primary_final) if primary_final else "",
            hashtags=episode.hashtags,
            drive_folder_url=drive_result.get("folder_url", ""),
            wa_token=wa_token,
            wa_user_id=wa_user_id,
            allow_env_fallback=allow_owner_wa_fallback,
        )

    return urdu_final, english_final

def main():
    parser = argparse.ArgumentParser(description="Multi-Channel Autonomous AI Video Agent")
    parser.add_argument(
        "--channel",
        type=str,
        default="body_simulator",
        choices=["all", "body_simulator", "xray_mechanics", "crazy_characters", "health_coach", "garage_guru", "code_classroom"],
        help="Target niche channel (or 'all' to run all 6 sequentially)"
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="english",
        choices=["english", "urdu", "both"],
        help="Which language to generate (saves TTS quota if not generating both)"
    )
    parser.add_argument("--mock", action="store_true", help="Run with mock clips for fast 0-credit test")
    parser.add_argument("--scenes", type=int, default=None, help="Number of scenes to render")
    parser.add_argument("--prompt", type=str, default=None, help="Optional custom user prompt / episode concept")
    parser.add_argument("--style", type=str, default=None, help="Optional visual style preset or custom style DNA")
    args = parser.parse_args()

    channels_to_run = (
        ["body_simulator", "xray_mechanics", "crazy_characters", "health_coach", "garage_guru", "code_classroom"]
        if args.channel == "all"
        else [args.channel]
    )

    for ch in channels_to_run:
        asyncio.run(produce_dual_language_episode(
            channel=ch,
            mock_video=args.mock,
            max_scenes=args.scenes,
            target_lang=args.lang,
            custom_prompt=args.prompt,
            visual_style=args.style,
        ))

if __name__ == "__main__":
    main()
