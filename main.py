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

from config import READY_TO_POST_DIR, TEMP_DIR, VOICE_PROVIDER, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
from voice.voice_engine import VoiceEngine
from voice.elevenlabs_engine import ElevenLabsEngine
from compositor.subtitles import SubtitleGenerator
from compositor.video_editor import VideoCompositor
from video_engine.pool_manager import FlowPoolManager
from brain.script_writer import ScriptWriter, VideoScript, Scene

def get_fallback_script(topic: str) -> VideoScript:
    """Provides a tailored high-CTR script when Gemini API is busy or hitting rate limits."""
    t_clean = topic.strip()
    return VideoScript(
        title=f"The Disturbing Reality of {t_clean}",
        topic=t_clean,
        viral_hook_type="Pattern Interrupt",
        full_audio_script=(
            f"You have been systematically lied to about {t_clean}. "
            "What they tell the public is an engineered distraction designed to keep you predictable and compliant. "
            f"Behind closed doors, the entire architecture of {t_clean} is calibrated to extract your attention and wealth. "
            "You are not making conscious choices here; you are just following a pre-programmed script. "
            "Are you ready to unplug from this illusion, or is ignorance more comfortable than the truth? Decide in the comments."
        ),
        scenes=[
            Scene(
                scene_num=1,
                audio_script=f"You have been systematically lied to about {t_clean}.",
                flow_prompt=f"Cinematic slow push-in shot of glowing neon hourglass in dark room, turquoise and magenta light beams, 8k vertical video"
            ),
            Scene(
                scene_num=2,
                audio_script="What they tell the public is an engineered distraction designed to keep you predictable and compliant.",
                flow_prompt=f"Dynamic low-angle orbital tilt around an ornate antique golden clock ticking in dense electric cyan mist and hot magenta backlight, 8k vertical video"
            ),
            Scene(
                scene_num=3,
                audio_script=f"Behind closed doors, the entire architecture of {t_clean} is calibrated to extract your attention and wealth.",
                flow_prompt=f"High-contrast aerial drone tracking shot over an infinite futuristic cyberpunk metropolis with blinding neon billboards in cyan and pink reflecting on wet streets, vertical 9:16"
            ),
            Scene(
                scene_num=4,
                audio_script="You are not making conscious choices here; you are just following a pre-programmed script.",
                flow_prompt=f"Macro close-up shot of an intricate cybernetic eye with glowing neon circuitry reflecting in the pupil, hyper-detailed iris, electric cyan and gold tones, vertical video"
            ),
            Scene(
                scene_num=5,
                audio_script="Are you ready to unplug from this illusion, or is ignorance more comfortable than the truth? Decide in the comments.",
                flow_prompt=f"Wide cinematic shot of a lone human silhouette standing at a nexus of diverging holographic neon pathways in an infinite dark chamber, vibrant magenta rim light, vertical video"
            )
        ],
        hashtags=["#DeepTruth", f"#{t_clean.replace(' ', '')}", "#MindBlown", "#Matrix", "#ViralShorts", "#WakeUp"],
        caption=f"Are you ready to rethink {t_clean}? Drop your verdict in the comments below."
    )

async def run_pipeline(topic: str, mock_video: bool = False, api_key: str = None, max_scenes: int = None):
    print("\n" + "=" * 65)
    print(" 🎬 AI VIDEO AUTOMATION PIPELINE (4x Google AI Pro Pool)")
    print("=" * 65)
    print(f"Topic: {topic}")
    print(f"Video Mode: {'Simulation / Mock Clips' if mock_video else 'Google Flow (Omni 1.1 Flash)'}")
    print("=" * 65 + "\n")

    start_total = time.time()

    # 1. BRAIN: Script Generation
    print("🧠 [1/5] BRAIN: Writing high-retention script and Veo prompts...")
    gemini_key = api_key or os.environ.get("GEMINI_API_KEY")
    script = None
    if gemini_key:
        try:
            writer = ScriptWriter(api_key=gemini_key)
            script = writer.generate_script(topic)
        except Exception as e:
            err_msg = str(e)
            if "503" in err_msg:
                print("ℹ️  Google AI Studio API is experiencing high demand (503). Using dynamic controversy engine...")
            elif "429" in err_msg:
                print("ℹ️  Google AI Studio API quota limit reached (429). Using dynamic controversy engine...")
            else:
                print(f"ℹ️  Gemini API notice: {err_msg[:60]}. Using dynamic controversy engine...")
            script = get_fallback_script(topic)
    else:
        print("ℹ️  No GEMINI_API_KEY detected. Using dynamic controversy engine...")
        script = get_fallback_script(topic)

    if max_scenes and max_scenes > 0:
        script.scenes = script.scenes[:max_scenes]

    print(f"    Title: {script.title}")
    print(f"    Hook Type: {script.viral_hook_type}")
    print(f"    Scenes to render: {len(script.scenes)}\n")

    # 2. VOICE: Speech Synthesis + Word Timestamps
    print("🎙️ [2/5] VOICE: Synthesizing voiceover & word timestamps...")
    voice_data = None
    if VOICE_PROVIDER == "elevenlabs" and ELEVENLABS_API_KEY:
        try:
            print("    Using ElevenLabs (Adam - Hyper-realistic human narration)...")
            eleven_engine = ElevenLabsEngine(api_key=ELEVENLABS_API_KEY, voice_id=ELEVENLABS_VOICE_ID)
            voice_data = eleven_engine.generate_speech(script.full_audio_script, output_prefix="master_narration")
        except Exception as e:
            print(f"ℹ️  ElevenLabs notice ({str(e)[:60]}...). Switching to expressive Edge-TTS voice...")
            voice_engine = VoiceEngine(voice="en-US-AndrewMultilingualNeural")
            voice_data = await voice_engine.generate_speech(script.full_audio_script, output_prefix="master_narration")
    else:
        print("    Using Edge-TTS (Expressive neural voice)...")
        voice_engine = VoiceEngine(voice="en-US-AndrewMultilingualNeural")
        voice_data = await voice_engine.generate_speech(script.full_audio_script, output_prefix="master_narration")

    print(f"    Audio duration: {voice_data['duration_seconds']:.2f}s")
    print(f"    Words aligned: {len(voice_data['words'])}\n")

    # 3. SUBTITLES: Neon ASS Subtitle Generation
    print("✨ [3/5] SUBTITLES: Formatting animated neon karaoke subtitles...")
    sub_gen = SubtitleGenerator()
    sub_path = sub_gen.generate_ass(voice_data["words"])
    print(f"    Subtitles saved: {sub_path}\n")

    # 4. VIDEO ENGINE: Parallel Generation Across 4 Accounts
    print("🎥 [4/5] VIDEO ENGINE: Dispatching scene prompts across 4 accounts...")
    pool = FlowPoolManager()
    prompts = [scene.flow_prompt for scene in script.scenes]
    clip_paths = await pool.render_scenes_parallel(prompts, mock_mode=mock_video)

    # 5. COMPOSITOR: FFmpeg 9:16 Assembly, Audio Mix, Subtitle Burn-in
    print("🎞️ [5/5] COMPOSITOR: Assembling 9:16 video, burning neon subtitles...")
    safe_topic = "".join(c for c in topic if c.isalnum() or c in (" ", "_")).rstrip().replace(" ", "_").lower()
    final_filename = f"short_{safe_topic}_{int(time.time())}.mp4"

    compositor = VideoCompositor()
    final_video = compositor.assemble_video(
        clip_paths=clip_paths,
        audio_path=voice_data["audio_path"],
        subtitles_path=str(sub_path),
        output_filename=final_filename
    )

    elapsed = time.time() - start_total
    print("\n" + "=" * 65)
    print(" 🎉 VIDEO GENERATION COMPLETE!")
    print("=" * 65)
    print(f" Output Video: {final_video}")
    print(f" Total Time:   {elapsed:.1f}s")
    print(f" Suggested Title: {script.title}")
    print(f" Caption:      {script.caption}")
    print(f" Hashtags:     {' '.join(script.hashtags)}")
    print("=" * 65 + "\n")

    # Save metadata info file alongside video
    meta_path = final_video.with_suffix(".txt")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(f"TITLE: {script.title}\n\n")
        f.write(f"CAPTION:\n{script.caption}\n\n")
        f.write(f"HASHTAGS:\n{' '.join(script.hashtags)}\n\n")
        f.write(f"AUDIO SCRIPT:\n{script.full_audio_script}\n")

    return final_video

def main():
    parser = argparse.ArgumentParser(description="AI Video Automation Pipeline (4x Google AI Pro)")
    parser.add_argument("--topic", type=str, default="The Illusion of Free Choice", help="Topic to generate video about")
    parser.add_argument("--scenes", type=int, default=None, help="Number of scenes to render (e.g. 1 or 2 for testing, default: all)")
    parser.add_argument("--mock", action="store_true", help="Run with mock video footage for rapid local testing")
    parser.add_argument("--api-key", type=str, default=None, help="Google AI Studio / Gemini API Key")
    args = parser.parse_args()

    asyncio.run(run_pipeline(topic=args.topic, mock_video=args.mock, api_key=args.api_key, max_scenes=args.scenes))

if __name__ == "__main__":
    main()
