import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
import edge_tts

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import TEMP_DIR

# Authentic Indian & Pakistani High-Expression Neural Voices
# These pronounce Hindi, Urdu, and English slang with authentic cadence
DESI_VOICE_CAST = {
    "stomach": {
        "voice": "hi-IN-MadhurNeural",
        "rate": "+12%",      # Faster, panic energy
        "pitch": "+10Hz"     # Higher cartoon voice
    },
    "brain": {
        "voice": "hi-IN-MadhurNeural",
        "rate": "+0%",       # Relaxed, lazy pacing
        "pitch": "-6Hz"      # Deeper, casual boss voice
    },
    "pancreas": {
        "voice": "hi-IN-MadhurNeural",
        "rate": "+15%",      # Rapid, stressed
        "pitch": "+14Hz"     # High comedic squeak
    },
    "aalu": {
        "voice": "hi-IN-MadhurNeural",
        "rate": "+5%",       # Sincere, emotional young hero
        "pitch": "+4Hz"
    },
    "narrator": {
        "voice": "ur-PK-AsadNeural",
        "rate": "+5%",       # Authoritative, dramatic documentary
        "pitch": "-2Hz"
    }
}

ENGLISH_VOICE_CAST = {
    "stomach": {
        "voice": "en-US-AndrewMultilingualNeural",
        "rate": "+12%",
        "pitch": "+10Hz"
    },
    "brain": {
        "voice": "en-US-BrianMultilingualNeural",
        "rate": "+2%",
        "pitch": "-6Hz"
    },
    "pancreas": {
        "voice": "en-US-GuyNeural",
        "rate": "+15%",
        "pitch": "+12Hz"
    },
    "narrator": {
        "voice": "en-US-ChristopherNeural",
        "rate": "+5%",
        "pitch": "-2Hz"
    }
}

class ExpressiveVoiceEngine:
    """
    Synthesizes authentic multi-character dialogue with dynamic emotional pitch/speed shifts,
    word-level timestamps for subtitles, and natural comic cadence.
    """

    async def _synthesize_line(self, voice_spec: Dict[str, str], text: str, output_file: Path) -> Dict[str, Any]:
        communicate = edge_tts.Communicate(
            text,
            voice=voice_spec["voice"],
            rate=voice_spec["rate"],
            pitch=voice_spec["pitch"],
            boundary="WordBoundary"
        )

        words = []
        with open(output_file, "wb") as f_out:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f_out.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start_ms = int(chunk["offset"] / 10000)
                    duration_ms = int(chunk["duration"] / 10000)
                    words.append({
                        "word": chunk["text"],
                        "start_ms": start_ms,
                        "end_ms": start_ms + duration_ms
                    })

        duration = words[-1]["end_ms"] / 1000.0 if words else 0.0
        return {"file": str(output_file), "words": words, "duration": duration}

    async def generate_dialogue_async(
        self,
        script_lines: List[Dict[str, str]],
        lang: str = "urdu",
        output_prefix: str = "dialogue_master"
    ) -> Dict[str, Any]:
        cast_map = DESI_VOICE_CAST if lang == "urdu" else ENGLISH_VOICE_CAST
        cumulative_ms = 0
        all_words = []
        files_to_join = []

        line_durations = []
        for idx, item in enumerate(script_lines):
            spk = item.get("speaker", "stomach").lower()
            spec = cast_map.get(spk, cast_map["stomach"])
            seg_file = TEMP_DIR / f"{output_prefix}_seg_{idx}.mp3"

            print(f"    Speaking [{spk.upper()} - {spec['voice']}]: '{item['line'][:45]}...'")
            seg_data = await self._synthesize_line(spec, item["line"], seg_file)
            files_to_join.append(Path(seg_data["file"]))
            line_durations.append(seg_data["duration"] + 0.12) # include natural pause

            for w in seg_data["words"]:
                all_words.append({
                    "word": w["word"],
                    "speaker": spk,
                    "start_ms": w["start_ms"] + cumulative_ms,
                    "end_ms": w["end_ms"] + cumulative_ms
                })

            # Natural dynamic comedic pause between speakers
            cumulative_ms += int(seg_data["duration"] * 1000) + 120

        master_audio = TEMP_DIR / f"{output_prefix}.mp3"
        concat_list = TEMP_DIR / f"{output_prefix}_concat.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in files_to_join:
                f.write(f"file '{p.as_posix()}'\n")

        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(master_audio)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        return {
            "audio_path": str(master_audio),
            "words": all_words,
            "line_durations": line_durations,
            "duration_seconds": cumulative_ms / 1000.0
        }


if __name__ == "__main__":
    eng = ExpressiveVoiceEngine()
    test_lines = [
        {"speaker": "stomach", "line": "Arre Maalik! Raat ke do baje biryani kaun mangwata hai?!"},
        {"speaker": "brain", "line": "Bhai bas do bite khayenge, chill kar na!"},
        {"speaker": "stomach", "line": "Chill kar?! Poora system blast hone wala hai yahan!"}
    ]
    res = asyncio.run(eng.generate_dialogue_async(test_lines, lang="urdu"))
    print("Desi Comedic Dialogue Audio Generated:", res["audio_path"])
    print("Duration:", res["duration_seconds"])
    print("Words Timed:", len(res["words"]))
