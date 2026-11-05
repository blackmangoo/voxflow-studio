import base64
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
import requests

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import TEMP_DIR

# Default to "Adam" (Dominant, firm, hyper-realistic viral narrator)
DEFAULT_ELEVEN_VOICE = "pNInz6obpgDQGcFmaJgB"

class ElevenLabsEngine:
    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: str = DEFAULT_ELEVEN_VOICE
    ):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "sk_0c09bf61cf51987d33ce5bbe662792d2110fb6e5430d7f31")
        self.voice_id = voice_id

    def _characters_to_words(
        self,
        characters: List[str],
        starts: List[float],
        ends: List[float]
    ) -> List[Dict[str, Any]]:
        """
        Converts ElevenLabs character-level timings into word-level millisecond timestamps.
        """
        words = []
        current_word = []
        word_start = None
        word_end = None

        for char, start_s, end_s in zip(characters, starts, ends):
            if char.isspace():
                if current_word:
                    w_str = "".join(current_word).strip()
                    if w_str:
                        words.append({
                            "word": w_str,
                            "start_ms": int(word_start * 1000),
                            "end_ms": int(word_end * 1000)
                        })
                    current_word = []
                    word_start = None
                    word_end = None
            else:
                if word_start is None:
                    word_start = start_s
                word_end = end_s
                current_word.append(char)

        if current_word:
            w_str = "".join(current_word).strip()
            if w_str:
                words.append({
                    "word": w_str,
                    "start_ms": int(word_start * 1000),
                    "end_ms": int(word_end * 1000)
                })

        return words

    def generate_speech(self, text: str, output_prefix: str = "eleven_narration") -> Dict[str, Any]:
        """
        Generates human speech audio and word timestamps using ElevenLabs with-timestamps API.
        """
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY is required.")

        audio_file = TEMP_DIR / f"{output_prefix}.mp3"
        json_file = TEMP_DIR / f"{output_prefix}_timestamps.json"

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/with-timestamps"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json"
        }

        # Optimized for dramatic viral pacing: slightly lower stability for expressive emotion
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.42,
                "similarity_boost": 0.85,
                "style": 0.25,
                "use_speaker_boost": True
            }
        }

        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(f"ElevenLabs API Error [{response.status_code}]: {response.text}")

        res_data = response.json()
        audio_bytes = base64.b64decode(res_data["audio_base64"])

        with open(audio_file, "wb") as f_out:
            f_out.write(audio_bytes)

        alignment = res_data.get("alignment", {})
        characters = alignment.get("characters", [])
        start_times = alignment.get("character_start_times_seconds", [])
        end_times = alignment.get("character_end_times_seconds", [])

        words = self._characters_to_words(characters, start_times, end_times)
        total_duration = words[-1]["end_ms"] / 1000.0 if words else 0.0

        result = {
            "audio_path": str(audio_file),
            "timestamps_path": str(json_file),
            "duration_seconds": total_duration,
            "words": words
        }

        with open(json_file, "w", encoding="utf-8") as j_out:
            json.dump(result, j_out, indent=2, ensure_ascii=False)

        return result


if __name__ == "__main__":
    test_text = "You have never made a truly free decision in your entire life."
    engine = ElevenLabsEngine()
    data = engine.generate_speech(test_text, "test_human_voice")
    print(f"Human audio generated: {data['audio_path']}")
    print(f"Duration: {data['duration_seconds']:.2f}s")
    print(f"Words parsed: {len(data['words'])}")
