import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Any

# Ensure project root is in path
ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import edge_tts
from config import DEFAULT_VOICE, VOICE_RATE, VOICE_PITCH, TEMP_DIR

class VoiceEngine:
    def __init__(self, voice: str = DEFAULT_VOICE, rate: str = VOICE_RATE, pitch: str = VOICE_PITCH):
        self.voice = voice
        self.rate = rate
        self.pitch = pitch

    async def generate_speech(self, text: str, output_prefix: str = "narration") -> Dict[str, Any]:
        """
        Generates MP3 audio and extracts exact word-level millisecond timestamps.
        Returns:
            {
                "audio_path": Path to generated .mp3,
                "timestamps_path": Path to .json with word timings,
                "duration_seconds": Total audio duration,
                "words": List of {"word": str, "start_ms": int, "end_ms": int}
            }
        """
        audio_file = TEMP_DIR / f"{output_prefix}.mp3"
        json_file = TEMP_DIR / f"{output_prefix}_timestamps.json"

        communicate = edge_tts.Communicate(
            text,
            self.voice,
            rate=self.rate,
            pitch=self.pitch,
            boundary="WordBoundary"
        )

        words = []
        with open(audio_file, "wb") as f_out:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f_out.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    # Offset and duration in edge-tts are in 100-nanosecond units (ticks)
                    start_ms = int(chunk["offset"] / 10000)
                    duration_ms = int(chunk["duration"] / 10000)
                    words.append({
                        "word": chunk["text"],
                        "start_ms": start_ms,
                        "end_ms": start_ms + duration_ms
                    })

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
    test_text = "The 8-hour sleep rule was never designed for human health. It was invented to maximize factory labor."
    engine = VoiceEngine()
    data = asyncio.run(engine.generate_speech(test_text, "test_voice"))
    print(f"Audio generated: {data['audio_path']}")
    print(f"Total duration: {data['duration_seconds']:.2f}s")
    print(f"Total words timed: {len(data['words'])}")
