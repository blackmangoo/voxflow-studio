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
from brain.body_simulator_brain import BodySimulatorBrain
from voice.character_voices import DialogueVoiceEngine
from compositor.modern_subtitles import ModernSubtitleGenerator
from compositor.video_editor import VideoCompositor
from video_engine.pool_manager import FlowPoolManager

OUTPUT_DIR = ROOT_DIR / "output" / "body_simulator"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

async def produce_body_simulator_episode(topic: str = None, mock_video: bool = False, max_scenes: int = None):
    print("\n" + "=" * 70)
    print(" 🎬 AUTONOMOUS AGENT: 'WHAT-IF' BODY SIMULATOR SHOWRUNNER")
    print("=" * 70)
    print(f"Mode: {'Simulation (Mock Clips)' if mock_video else 'Google Flow (Omni 1.1 Flash - 10s Clips)'}")
    print(f"Output Directory: {OUTPUT_DIR}")
    print("=" * 70 + "\n")

    start_time = time.time()

    # 1. BRAIN: Dynamic Ideation & Scripting (Gemini API)
    print("🧠 [1/5] BRAIN: Ideating 'What If' body transformation scenario...")
    brain = BodySimulatorBrain()
    episode = brain.generate_episode(custom_topic=topic)

    scene_prompts = [s.flow_prompt for s in episode.scenes]
    if max_scenes and max_scenes > 0:
        scene_prompts = scene_prompts[:max_scenes]
        episode.scenes = episode.scenes[:max_scenes]
        episode.dialogue = episode.dialogue[:max_scenes]

    print(f"    Title: {episode.title}")
    print(f"    Topic: {episode.topic}")
    print(f"    Scenes to Render: {len(scene_prompts)}\n")

    # 2. VOICE: Multi-Character Voice Cast (ElevenLabs)
    print("🎙️ [2/5] VOICE: Synthesizing multi-organ voice cast...")
    dialogue_engine = DialogueVoiceEngine()
    dialogue_payload = [{"speaker": d.speaker, "line": d.line} for d in episode.dialogue]
    voice_data = dialogue_engine.generate_dialogue(dialogue_payload, output_prefix="body_dialogue_master")

    print(f"    Total Audio Duration: {voice_data['duration_seconds']:.2f}s")
    print(f"    Words Aligned: {len(voice_data['words'])}\n")

    # 3. SUBTITLES: Lower-Third Modern Reel Subtitles
    print("✨ [3/5] SUBTITLES: Generating lower-third bouncy reel captions...")
    sub_gen = ModernSubtitleGenerator()
    sub_path = sub_gen.generate_ass(voice_data["words"], output_path=TEMP_DIR / "body_subtitles.ass")
    print(f"    Subtitles compiled: {sub_path}\n")

    # 4. VIDEO ENGINE: Render 10s Character Clips on Google Flow (Omni 1.1 Flash)
    print(f"🎥 [4/5] VIDEO ENGINE: Dispatching {len(scene_prompts)} scenes (10s each) across Google AI pool...")
    pool = FlowPoolManager()
    clip_paths = await pool.render_scenes_parallel(scene_prompts, mock_mode=mock_video)

    # 5. COMPOSITOR: Assembling 9:16 vertical video
    print("🎞️ [5/5] COMPOSITING: Assembling final vertical video + subtitles...")
    safe_topic = "".join(c for c in episode.topic if c.isalnum() or c in (" ", "_")).strip().replace(" ", "_").lower()[:30]
    final_video_name = f"body_sim_{safe_topic}_{int(time.time())}.mp4"
    final_video_path = OUTPUT_DIR / final_video_name

    compositor = VideoCompositor()
    rendered_file = compositor.assemble_video(
        clip_paths=clip_paths,
        audio_path=voice_data["audio_path"],
        subtitles_path=str(sub_path),
        output_filename=final_video_name
    )

    if Path(rendered_file).parent != OUTPUT_DIR:
        destination = OUTPUT_DIR / final_video_name
        import shutil
        shutil.move(rendered_file, destination)
        final_video_path = destination
    else:
        final_video_path = Path(rendered_file)

    # Save ready-to-post metadata file
    full_script_text = "\n".join([f"[{d.speaker.upper()}]: {d.line}" for d in episode.dialogue])
    meta_file = final_video_path.with_suffix(".txt")
    with open(meta_file, "w", encoding="utf-8") as f:
        f.write(f"TITLE:\n{episode.title}\n\n")
        f.write(f"CAPTION:\n{episode.caption}\n\n")
        f.write(f"HASHTAGS:\n{' '.join(episode.hashtags)}\n\n")
        f.write(f"DIALOGUE SCRIPT:\n{full_script_text}\n")

    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print(" 🎉 WHAT-IF BODY SIMULATOR EPISODE COMPLETE!")
    print("=" * 70)
    print(f" Output Video: {final_video_path}")
    print(f" Metadata:     {meta_file}")
    print(f" Total Time:   {elapsed:.1f}s")
    print(f" Suggested Title: {episode.title}")
    print("=" * 70 + "\n")

    return final_video_path

def main():
    parser = argparse.ArgumentParser(description="Autonomous What-If Body Simulator Agent")
    parser.add_argument("--topic", type=str, default=None, help="Custom topic, e.g., 'What if you gym 30 mins daily', or leave empty for autonomous ideation")
    parser.add_argument("--mock", action="store_true", help="Run with mock clips for fast testing")
    parser.add_argument("--scenes", type=int, default=None, help="Number of scenes to render")
    args = parser.parse_args()

    asyncio.run(produce_body_simulator_episode(topic=args.topic, mock_video=args.mock, max_scenes=args.scenes))

if __name__ == "__main__":
    main()
