import os
import random
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS, TEMP_DIR, READY_TO_POST_DIR


class VideoCompositor:
    """
    Millisecond-accurate video assembly pipeline:

    1. Each visual clip is scaled/cropped to 1080x1920 @ 30fps and cut/looped to match
       the EXACT duration of its corresponding dialogue line.
    2. Vocal audio: 80Hz high-pass -> dynamic compression -> loudness normalisation (EBU R128).
    3. BGM sidechain ducking: BGM drops to 12% volume during spoken lines, rises to 45%
       in the gaps between lines. Timestamps are derived from scene_durations.
    4. SFX whooshes fire at every scene transition.
    5. ASS subtitles burned in (per-channel brand style via ModernSubtitleGenerator).
    6. Thumbnail extracted at 30% into the final video.
    """

    def __init__(self):
        self.width  = VIDEO_WIDTH
        self.height = VIDEO_HEIGHT
        self.fps    = VIDEO_FPS

    def get_media_duration(self, file_path: str) -> float:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        return float(result.stdout.strip())

    def _build_duck_filter(self, scene_durations: List[float], bgm_label: str) -> str:
        """
        Builds a frame-evaluated FFmpeg `volume` filter that ducks BGM to 0.12 during
        spoken lines and raises it to 0.45 during inter-line pauses.
        """
        GAP = 0.18
        segments = []
        t = 0.0
        for dur in scene_durations:
            speech_dur = max(dur - GAP, 0.1)
            segments.append((t, t + speech_dur))
            t += dur

        if not segments:
            return f"{bgm_label}volume=0.18[bgm_ducked]"

        during_speech = "+".join(
            f"between(t,{s:.3f},{e:.3f})" for s, e in segments
        )

        return (
            f"{bgm_label}"
            f"volume='if(gt({during_speech},0),0.12,0.45)':eval=frame"
            f"[bgm_ducked]"
        )

    def assemble_video_synced(
        self,
        clip_paths: List[str],
        audio_path: str,
        scene_durations: List[float],
        subtitles_path: Optional[str] = None,
        music_path: Optional[str] = None,
        output_filename: str = "final_short.mp4",
        channel: Optional[str] = None,
    ) -> Path:
        if Path(output_filename).is_absolute() or "/" in str(output_filename) or "\\" in str(output_filename):
            final_output = Path(output_filename)
        else:
            final_output = TEMP_DIR / output_filename
        final_output.parent.mkdir(parents=True, exist_ok=True)

        total_audio_duration = self.get_media_duration(audio_path)
        num_clips = len(clip_paths)
        if num_clips == 0:
            raise ValueError("No video clips provided.")

        if len(scene_durations) != num_clips:
            duration_per_clip = max(0.5, total_audio_duration / num_clips)
            scene_durations = [duration_per_clip] * num_clips
        else:
            scene_durations = [max(0.5, float(d)) for d in scene_durations]

        # ── 1. Normalize each clip to its exact line duration (preserving real motion) ──
        tag = f"{channel or 'ch'}_{os.getpid()}_{random.randint(100,999)}"
        processed_clips = []
        concat_txt = TEMP_DIR / f"synced_{tag}_concat.txt"
        stitched_video = TEMP_DIR / f"stitched_{tag}_synced.mp4"

        try:
            for idx, (clip, dur) in enumerate(zip(clip_paths, scene_durations)):
                out_clip = TEMP_DIR / f"synced_{tag}_clip_{idx}.mp4"
                vf = (
                    f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
                    f"crop={self.width}:{self.height},"
                    f"fps={self.fps},setsar=1"
                )
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-stream_loop", "-1",
                        "-i", str(clip),
                        "-t", f"{dur:.3f}",
                        "-vf", vf,
                        "-an",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                        str(out_clip)
                    ],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
                )
                processed_clips.append(str(out_clip))

            # ── 2. Concatenate normalized clips ────────────────────────────────
            with open(concat_txt, "w", encoding="utf-8") as f:
                for p in processed_clips:
                    f.write(f"file '{Path(p).as_posix()}'\n")

            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", str(stitched_video)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )

            # ── 3. Build filter_complex ────────────────────────────────────────
            vocal_filter = (
                "highpass=f=80,"
                "compand=attacks=0.02:decays=0.2:points=-80/-80|-40/-30|-20/-15|0/-10,"
                "loudnorm=I=-16:TP=-1.5:LRA=11,"
                "aresample=44100"
            )

            sub_filter = ""
            if subtitles_path and Path(subtitles_path).exists():
                clean_sub = (
                    Path(subtitles_path)
                    .as_posix()
                    .replace("\\", "/")
                    .replace(":", "\\:")
                    .replace("'", "\\'")
                )
                sub_filter = f"ass='{clean_sub}'"

            from video_engine.asset_fetcher import get_random_audio
            sfx_path = get_random_audio(ROOT_DIR / "assets" / "sfx")
            sfx_delays = []
            if sfx_path:
                t = 0.0
                for dur in scene_durations[:-1]:
                    t += dur
                    sfx_delays.append(int(t * 1000))

            final_cmd = ["ffmpeg", "-y", "-i", str(stitched_video), "-i", str(audio_path)]
            filter_complex = []
            video_map = "0:v"

            if sub_filter:
                filter_complex.append(f"[{video_map}]{sub_filter}[v_out]")
                video_map = "[v_out]"

            filter_complex.append(f"[1:a]{vocal_filter}[vocal]")

            if sfx_delays and sfx_path:
                final_cmd.extend(["-i", str(sfx_path)])
                sfx_idx = 2
                n_sfx = len(sfx_delays)
                if n_sfx > 1:
                    split_outs = "".join(f"[sfx_src_{i}]" for i in range(n_sfx))
                    filter_complex.append(f"[{sfx_idx}:a]asplit={n_sfx}{split_outs}")
                delayed = []
                for i, delay in enumerate(sfx_delays):
                    src_pad = f"[sfx_src_{i}]" if n_sfx > 1 else f"[{sfx_idx}:a]"
                    filter_complex.append(
                        f"{src_pad}adelay={delay}:all=1[sfx_d_{i}];"
                        f"[sfx_d_{i}]aresample=44100,volume=0.35[sfx_{i}]"
                    )
                    delayed.append(f"[sfx_{i}]")
                amix_in = "[vocal]" + "".join(delayed)
                filter_complex.append(
                    f"{amix_in}amix=inputs={1 + len(delayed)}:duration=first:dropout_transition=2:normalize=0[vocal_sfx]"
                )
                main_audio = "[vocal_sfx]"
                bgm_idx = 3
            else:
                main_audio = "[vocal]"
                bgm_idx = 2

            if music_path and Path(music_path).exists():
                bgm_duration = self.get_media_duration(music_path)
                start_offset = 0
                if bgm_duration > total_audio_duration + 10:
                    start_offset = random.randint(2, max(2, int(bgm_duration - total_audio_duration - 2)))
                final_cmd.extend(["-stream_loop", "-1", "-ss", str(start_offset), "-i", str(music_path)])

                duck_filter = self._build_duck_filter(scene_durations, f"[{bgm_idx}:a]aresample=44100,")
                filter_complex.append(duck_filter)
                filter_complex.append(
                    f"{main_audio}[bgm_ducked]amix=inputs=2:duration=first:dropout_transition=1:normalize=0[a_out]"
                )
                audio_map = "[a_out]"
            else:
                filter_complex.append(f"{main_audio}anull[a_out]")
                audio_map = "[a_out]"

            final_cmd.extend(["-filter_complex", ";".join(filter_complex)])
            final_cmd.extend([
                "-map", video_map,
                "-map", audio_map,
                "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                "-c:a", "aac", "-b:a", "192k",
                "-t", f"{total_audio_duration:.3f}",
                str(final_output)
            ])

            subprocess.run(final_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

            # ── 4. Thumbnail at 30% ────────────────────────────────────────────
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(total_audio_duration * 0.3),
                 "-i", str(final_output), "-vframes", "1", "-q:v", "2",
                 str(final_output.with_suffix(".jpg"))],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        finally:
            # Clean up intermediate per-run synced clips even on exception
            for p in processed_clips:
                Path(p).unlink(missing_ok=True)
            concat_txt.unlink(missing_ok=True)
            stitched_video.unlink(missing_ok=True)

        return final_output

    def assemble_video(self, *args, **kwargs):
        """Backward-compatible alias."""
        return self.assemble_video_synced(*args, **kwargs)


if __name__ == "__main__":
    print("VideoCompositor ready — BGM ducking + per-line sync active.")
