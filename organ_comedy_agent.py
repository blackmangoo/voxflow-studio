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
from brain.organ_comedy_brain import OrganComedyBrain
from voice.character_voices import DialogueVoiceEngine
from compositor.modern_subtitles import ModernSubtitleGenerator
from compositor.video_editor import VideoCompositor
from video_engine.pool_manager import FlowPoolManager

ORGAN_COMEDY_DIR = ROOT_DIR / "output" / "organ_comedy"
ORGAN_COMEDY_DIR.mkdir(parents=True, exist_ok=True)

async def produce_organ_comedy_episode(mock_video: bool = False, max_scenes: int = None):
    print("\n" + "=" * 70)
    print(" 🎬 AUTONOMOUS AGENT: MULTI-CHARACTER ORGAN COMEDY")
    print("=" * 70)
    print(f"Mode: {'Simulation (Mock Clips)' if mock_video else 'Google Flow (Omni 1.1 Flash)'}")
    print(f"Output Directory: {ORGAN_COMEDY_DIR}")
    print("=" * 70 + "\n")

    start_time = time.time()

    # 1. BRAIN: Autonomous Storyboard & Multi-Character Dialogue
    print("🧠 [1/5] IDEATING EPISODE: Selecting unrepeated scenario & dialogue...")
    brain = OrganComedyBrain()
    episode = brain.generate_autonomous_episode()

    scene_prompts = episode.scene_prompts
    if max_scenes and max_scenes > 0:
        scene_prompts = scene_prompts[:max_scenes]

    print(f"    Title: {episode.title}")
    print(f"    Food: {episode.food}")
    print(f"    Dialogue Lines: {len(episode.dialogue)}")
    print(f"    Scenes to Render: {len(scene_prompts)}\n")

    # 2. VOICE: Multi-Character Dialogue Synthesis (ElevenLabs)
    print("🎙️ [2/5] VOICE: Synthesizing multi-character dialogue with distinct voices...")
    dialogue_engine = DialogueVoiceEngine()
    voice_data = dialogue_engine.generate_dialogue(episode.dialogue, output_prefix="organ_dialogue_master")

    print(f"    Total Audio Duration: {voice_data['duration_seconds']:.2f}s")
    print(f"    Words Aligned: {len(voice_data['words'])}\n")

    # 3. SUBTITLES: Lower-Third Modern Reel Subtitles (Never covers character face)
    print("✨ [3/5] SUBTITLES: Formatting modern lower-third reel captions...")
    sub_gen = ModernSubtitleGenerator()
    sub_path = sub_gen.generate_ass(voice_data["words"], output_path=TEMP_DIR / "modern_organ_subtitles.ass")
    print(f"    Subtitles compiled: {sub_path}\n")

    # 4. VIDEO ENGINE: Render Character Clips on Google Flow
    print(f"🎥 [4/5] VIDEO ENGINE: Dispatching {len(scene_prompts)} scene prompts to Google Flow...")
    pool = FlowPoolManager()
    clip_paths = await pool.render_scenes_parallel(scene_prompts, mock_mode=mock_video)

    # 5. COMPOSITOR: Stitching vertical 9:16 video + subtitles
    print("🎞️ [5/5] COMPOSITING: Assembling final 9:16 vertical short...")
    safe_title = "".join(c for c in episode.food if c.isalnum() or c in (" ", "_")).strip().replace(" ", "_").lower()
    final_video_name = f"reel_{safe_title}_{int(time.time())}.mp4"
    final_video_path = ORGAN_COMEDY_DIR / final_video_name

    compositor = VideoCompositor()
    rendered_file = compositor.assemble_video(
        clip_paths=clip_paths,
        audio_path=voice_data["audio_path"],
        subtitles_path=str(sub_path),
        output_filename=final_video_name
    )

    if Path(rendered_file).parent != ORGAN_COMEDY_DIR:
        destination = ORGAN_COMEDY_DIR / final_video_name
        import shutil
        shutil.move(rendered_file, destination)
        final_video_path = destination
    else:
        final_video_path = Path(rendered_file)

    # Save ready-to-post metadata file
    full_script_text = "\n".join([f"[{d['speaker'].upper()}]: {d['line']}" for d in episode.dialogue])
    meta_file = final_video_path.with_suffix(".txt")
    with open(meta_file, "w", encoding="utf-8") as f:
        f.write(f"TITLE:\n{episode.title}\n\n")
        f.write(f"CAPTION:\n{episode.caption}\n\n")
        f.write(f"HASHTAGS:\n{' '.join(episode.hashtags)}\n\n")
        f.write(f"DIALOGUE SCRIPT:\n{full_script_text}\n")

    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print(" 🎉 AUTONOMOUS EPISODE COMPLETED!")
    print("=" * 70)
    print(f" Output Video: {final_video_path}")
    print(f" Metadata:     {meta_file}")
    print(f" Total Time:   {elapsed:.1f}s")
    print(f" Suggested Title: {episode.title}")
    print("=" * 70 + "\n")

    return final_video_path

def main():
    parser = argparse.ArgumentParser(description="Autonomous Multi-Character Organ Comedy Agent")
    parser.add_argument("--mock", action="store_true", help="Run with mock video for fast dry run")
    parser.add_argument("--scenes", type=int, default=None, help="Number of scenes to render (default: all)")
    args = parser.parse_args()

    asyncio.run(produce_organ_comedy_episode(mock_video=args.mock, max_scenes=args.scenes))

if __name__ == "__main__":
    main()
