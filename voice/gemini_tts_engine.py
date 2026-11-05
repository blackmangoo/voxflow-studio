import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import TEMP_DIR, GEMINI_TTS_KEYS
from google import genai
from google.genai import types

# Gemini 3.8 Flash TTS Voices:
# - "Puck": Higher pitch, dynamic, youthful, animated, fast comedic energy
# - "Charon": Deep, authoritative baritone, cinematic narrator
# - "Fenrir": Gritty, raspy, textured, dramatic
# - "Kore": Warm, expressive female
# - "Zephyr": Crisp, neutral, clear
GEMINI_VOICE_CAST = {
    "stomach": {
        "voice": "Puck",
        "style": "Panicked, comedic cartoon character screaming in frustration, breathless high-energy delivery"
    },
    "brain": {
        "voice": "Charon",
        "style": "Deep, relaxed, lazy boss speaking in casual dismissive tone with slight humor"
    },
    "pancreas": {
        "voice": "Puck",
        "style": "Stressed, frantic logistics clerk shouting about emergency overtime"
    },
    "aalu": {
        "voice": "Puck",
        "style": "Emotional, sincere young desi hero speaking with proud motivational passion"
    },
    "tamatar": {
        "voice": "Charon",
        "style": "Chubby funny desi uncle or proud shopkeeper with enthusiastic street banter"
    },
    "narrator": {
        "voice": "Charon",
        "style": "Deep, authoritative, cinematic science documentary narrator with gripping suspense"
    },
    "mechanic": {
        "voice": "Fenrir",
        "style": "Experienced garage master mechanic with serious, cautionary, gritty engineering tone"
    }
}

class GeminiFlashTTSEngine:
    """
    Direct client for Gemini 3.8 Flash TTS:
    - High-emotion natural human/cartoon acting
    - Direct 24kHz Studio Audio output
    - Zero robotic cadence
    """

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or (GEMINI_TTS_KEYS[0] if GEMINI_TTS_KEYS else os.environ.get("GEMINI_API_KEY", ""))
        self.client = genai.Client(
            api_key=self.api_key,
            http_options={"headers": {"User-Agent": "aistudio-build"}}
        )

    def synthesize_line(self, voice_name: str, style_directive: str, text: str, output_path: Path) -> float:
        contents = [{
            "role": "user",
            "parts": [{
                "text": text,
                "speechMetadata": {
                    "style": style_directive
                }
            }]
        }]

        speech_config = {
            "voiceConfig": {
                "prebuiltVoiceConfig": {"voiceName": voice_name}
            }
        }

        response = self.client.models.generate_content(
            model="gemini-3.8-flash-tts",
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=speech_config
            )
        )

        part = response.candidates[0].content.parts[0]
        audio_data = part.inline_data.data
        audio_bytes = base64.b64decode(audio_data) if isinstance(audio_data, str) else audio_data

        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        # Get exact duration via ffprobe
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(output_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())

    async def generate_dialogue_async(
        self,
        script_lines: List[Dict[str, str]],
        lang: str = "urdu",
        output_prefix: str = "gemini_tts_dialogue"
    ) -> Dict[str, Any]:
        cumulative_ms = 0
        all_words = []
        files_to_join = []
        line_durations = []

        for idx, item in enumerate(script_lines):
            spk = item.get("speaker", "stomach").lower()
            spec = GEMINI_VOICE_CAST.get(spk, GEMINI_VOICE_CAST["stomach"])
            seg_file = TEMP_DIR / f"{output_prefix}_seg_{idx}.wav"

            print(f"    Speaking [{spk.upper()} - Gemini 3.8 Flash TTS ({spec['voice']})]: '{item['line'][:45]}...'")
            duration = self.synthesize_line(spec["voice"], spec["style"], item["line"], seg_file)
            files_to_join.append(seg_file)
            line_durations.append(duration + 0.12)

            # Generate synthetic word timestamps proportional to duration
            words_in_line = item["line"].split()
            if words_in_line:
                ms_per_word = int((duration * 1000) / len(words_in_line))
                for w_idx, w in enumerate(words_in_line):
                    w_start = cumulative_ms + (w_idx * ms_per_word)
                    w_end = w_start + ms_per_word
                    all_words.append({
                        "word": w,
                        "speaker": spk,
                        "start_ms": w_start,
                        "end_ms": w_end
                    })

            cumulative_ms += int(duration * 1000) + 120

        master_audio = TEMP_DIR / f"{output_prefix}.wav"
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
    engine = GeminiFlashTTSEngine()
    test_lines = [
        {"speaker": "stomach", "line": "Arrey Maalik! Raat ke do baje biryani kaun mangwata hai?!"},
        {"speaker": "brain", "line": "Bhai bas do bite khayenge, chill kar na!"},
        {"speaker": "stomach", "line": "Chill kar?! Poora system blast hone wala hai yahan!"}
    ]
    import asyncio
    res = asyncio.run(engine.generate_dialogue_async(test_lines))
    print(f"Master Gemini Audio Generated: {res['audio_path']} (Duration: {res['duration_seconds']:.2f}s)")
