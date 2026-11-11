import base64
import hashlib
import os
import random
import subprocess
import sys
import wave
from pathlib import Path
from typing import List, Dict, Any, Optional

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import TEMP_DIR, GEMINI_TTS_KEYS
from voice.audio_dsp import stitch_segments_clean
from google import genai
from google.genai import types

VOICE_CONFIGS = {
    # ── Urdu / Desi personas ──────────────────────────────────────────────────
    "mehak":    {"voice": "Kore",   "edge_voice": "ur-PK-UzmaNeural",        "pitch": "+8Hz",  "rate": "+4%",  "style": "Soft, delicate nazaakat with lingering romantic warmth, gentle sighs"},
    "farhan":   {"voice": "Charon", "edge_voice": "ur-PK-AsadNeural",        "pitch": "-4Hz",  "rate": "+2%",  "style": "Deep, velvety, soulful Urdu romantic baritone with poetic tehzeeb"},
    "stomach":  {"voice": "Puck",   "edge_voice": "ur-PK-AsadNeural",        "pitch": "+12Hz", "rate": "+12%", "style": "High-pitched comedic screaming, frantic rapid breaths, breathless cartoon panic"},
    "pancreas": {"voice": "Puck",   "edge_voice": "ur-PK-AsadNeural",        "pitch": "+14Hz", "rate": "+15%", "style": "Stressed, frantic logistics clerk shouting about emergency overtime"},
    "kidney":   {"voice": "Puck",   "edge_voice": "ur-PK-AsadNeural",        "pitch": "+10Hz", "rate": "+8%",  "style": "Panicked lab chemist realizing a critical chemical shortage, dramatic whispered alarm"},
    "heart":    {"voice": "Puck",   "edge_voice": "ur-PK-AsadNeural",        "pitch": "+6Hz",  "rate": "+20%", "style": "Hyper-energetic thumping athlete character, out of breath, rapid excited delivery"},
    "muscle":   {"voice": "Fenrir", "edge_voice": "ur-PK-AsadNeural",        "pitch": "-2Hz",  "rate": "+8%",  "style": "Pumped gym bro energy, loud, flexing confidence with grunting effort"},
    "aalu":     {"voice": "Puck",   "edge_voice": "ur-PK-AsadNeural",        "pitch": "+4Hz",  "rate": "+6%",  "style": "Emotional, sincere young desi hero speaking with proud motivational passion"},
    "tamatar":  {"voice": "Charon", "edge_voice": "ur-PK-AsadNeural",        "pitch": "-6Hz",  "rate": "+2%",  "style": "Chubby funny desi uncle or street vendor with enthusiastic banter"},
    "pyaaz":    {"voice": "Puck",   "edge_voice": "ur-PK-AsadNeural",        "pitch": "+2Hz",  "rate": "+4%",  "style": "Dramatic crying onion character, tears in the voice, layered emotional sadness"},
    "mirchi":   {"voice": "Puck",   "edge_voice": "ur-PK-AsadNeural",        "pitch": "+16Hz", "rate": "+18%", "style": "Fiery hot-headed short-tempered chili character, super fast aggressive delivery"},
    "chai":     {"voice": "Aoede",  "edge_voice": "ur-PK-UzmaNeural",        "pitch": "+4Hz",  "rate": "+2%",  "style": "Warm cozy desi auntie energy, comforting, slightly gossip tone"},
    "brain":    {"voice": "Charon", "edge_voice": "ur-PK-AsadNeural",        "pitch": "-6Hz",  "rate": "+0%",  "style": "Deep condescending boss, calm sarcastic authority, relaxed dismissive tone"},

    # ── English personas ──────────────────────────────────────────────────────
    "melody":        {"voice": "Aoede",  "edge_voice": "en-US-JennyNeural",       "pitch": "+6Hz",  "rate": "+4%",  "style": "Silky, honeyed softness, playful flirty teasing, seductive close-mic whisper"},
    "narrator":      {"voice": "Charon", "edge_voice": "en-US-ChristopherNeural", "pitch": "-2Hz",  "rate": "+4%",  "style": "Deep, authoritative, cinematic science documentary narrator with gripping suspense"},
    "mechanic":      {"voice": "Fenrir", "edge_voice": "en-US-GuyNeural",         "pitch": "-4Hz",  "rate": "+2%",  "style": "Experienced gritty master mechanic, serious cautionary engineering tone, battle-hardened"},
    "doctor":        {"voice": "Charon", "edge_voice": "en-US-ChristopherNeural", "pitch": "-3Hz",  "rate": "+2%",  "style": "Warm, trustworthy medical expert voice. Evidence-based, authoritative but approachable. Slight urgency for health warnings"},
    "cpp_professor": {"voice": "Fenrir", "edge_voice": "en-US-GuyNeural",         "pitch": "-5Hz",  "rate": "+6%",  "style": "Brilliant sarcastic CS professor. Brutally honest, witty, challenging, slightly exasperated tone with dry humor"},
    "student":       {"voice": "Puck",   "edge_voice": "en-US-SteffanNeural",     "pitch": "+8Hz",  "rate": "+8%",  "style": "Confused, eager, slightly overwhelmed BS student. Natural young voice, genuine curiosity mixed with mild panic"},
}

SPEAKER_ALIASES = {
    # Urdu
    "female": "mehak", "girl": "mehak", "heroine": "mehak",
    "hero": "aalu",    "poet": "farhan", "veggie_hero": "aalu",
    "karan": "farhan",
    # English
    "female_en": "melody", "host": "narrator", "engineer": "mechanic",
    "professor": "cpp_professor", "teacher": "cpp_professor",
    "doc": "doctor", "health_expert": "doctor",
    "garage": "mechanic", "gearhead": "mechanic",
}

GEMINI_TTS_MODELS = [
    "gemini-2.5-flash-preview-tts",
    "gemini-3.1-flash-tts-preview",
    "gemini-3.8-flash-lite-tts",
    "gemini-3.8-flash-tts",
]


def _normalize_to_pcm24k_wav(audio_bytes: bytes, output_wav: Path) -> None:
    """
    Ensures audio_bytes (whether RIFF WAV or raw 24kHz 16-bit mono PCM)
    is written as a standard 24000Hz mono 16-bit PCM WAV file for audio_dsp.py.
    """
    raw_tmp = output_wav.with_suffix(".raw_tts")
    try:
        if audio_bytes[:4] == b"RIFF":
            with open(raw_tmp, "wb") as f:
                f.write(audio_bytes)
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(raw_tmp), "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(output_wav)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )
        else:
            # Raw L16 24000Hz mono PCM without header
            with wave.open(str(output_wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(audio_bytes)
    finally:
        raw_tmp.unlink(missing_ok=True)


class GeminiTTSPool:
    """
    Rotating pool of Gemini TTS API keys across 4 Gemini TTS models.
    On 429/503 rotates across models and keys before falling back to Edge-TTS.
    """

    def __init__(self, keys: List[str]):
        self.keys = keys
        self._idx = 0
        self._exhausted: set = set()
        self._build_client()

    def _build_client(self):
        self.client = genai.Client(
            api_key=self.keys[self._idx],
            http_options=types.HttpOptions(
                timeout=15000,
                headers={"User-Agent": "aistudio-build"},
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def _advance(self) -> bool:
        self._exhausted.add(self._idx)
        for offset in range(1, len(self.keys)):
            candidate = (self._idx + offset) % len(self.keys)
            if candidate not in self._exhausted:
                self._idx = candidate
                self._build_client()
                print(f"    [TTS Pool] Rotated to key #{self._idx + 1} ({len(self._exhausted)}/{len(self.keys)} exhausted)")
                return True
        return False

    def generate_tts(self, voice_name: str, style: str, text: str, output_wav: Path) -> float:
        prompt_text = f"Say in a {style.strip()} tone: {text}" if style and style.strip() else text
        while True:
            last_err = None
            for model_name in GEMINI_TTS_MODELS:
                try:
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=[{
                            "role": "user",
                            "parts": [{"text": prompt_text}]
                        }],
                        config=types.GenerateContentConfig(
                            response_modalities=["AUDIO"],
                            speech_config=types.SpeechConfig(
                                voice_config=types.VoiceConfig(
                                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                                )
                            )
                        )
                    )
                    part = response.candidates[0].content.parts[0]
                    audio_data = part.inline_data.data
                    audio_bytes = base64.b64decode(audio_data) if isinstance(audio_data, str) else audio_data

                    _normalize_to_pcm24k_wav(audio_bytes, output_wav)
                    return _probe_duration(output_wav)

                except Exception as e:
                    last_err = e
                    err = str(e).lower()
                    if "503" in err or "unavailable" in err or "not found" in err:
                        # Try next TTS model on the same key
                        continue
                    if "429" in err or "quota" in err or "rate limit" in err or "exhausted" in err:
                        # Try next TTS model first; if all models on this key are 429, rotate key
                        continue
                    raise

            # All models failed on current key — advance to next key in pool
            err_str = str(last_err).lower() if last_err else ""
            if any(k in err_str for k in ("429", "quota", "rate limit", "exhausted", "503", "unavailable")):
                if not self._advance():
                    raise RuntimeError("All Gemini TTS keys/models exhausted — falling back to Edge-TTS.")
            else:
                raise last_err or RuntimeError("Gemini TTS failed")


def _character_rng(character_key: str) -> random.Random:
    import time
    hour_bucket = int(time.time()) // 3600
    seed = int(hashlib.md5(character_key.encode()).hexdigest(), 16) ^ hour_bucket
    return random.Random(seed)


def _edge_tts_variation(character_key: str, base_rate: str, base_pitch: str) -> tuple:
    rng = _character_rng(character_key)

    rate_val = int(base_rate.replace("%", "").replace("+", "").replace("-", ""))
    rate_sign = -1 if base_rate.startswith("-") else 1
    new_rate_val = rate_val * rate_sign + rng.randint(-2, 2)
    new_rate = f"+{new_rate_val}%" if new_rate_val >= 0 else f"{new_rate_val}%"

    pitch_val = int(base_pitch.replace("Hz", "").replace("+", "").replace("-", ""))
    pitch_sign = -1 if base_pitch.startswith("-") else 1
    new_pitch_val = pitch_val * pitch_sign + rng.randint(-2, 2)
    new_pitch = f"+{new_pitch_val}Hz" if new_pitch_val >= 0 else f"{new_pitch_val}Hz"

    return new_rate, new_pitch


def _probe_duration(wav_path: Path) -> float:
    try:
        with wave.open(str(wav_path), "rb") as w:
            rate = w.getframerate()
            if rate > 0:
                return float(w.getnframes()) / float(rate)
    except Exception:
        pass
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(wav_path)],
            capture_output=True, text=True, check=True
        )
        return float(res.stdout.strip())
    except Exception:
        return max(1.0, float(wav_path.stat().st_size) / 48000.0) if wav_path.exists() else 2.0


async def asyncio_to_thread_ffmpeg(mp3_temp: Path, output_wav: Path) -> None:
    import asyncio
    def _conv():
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(mp3_temp), "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(output_wav)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
    await asyncio.to_thread(_conv)


class VoxStudioEngine:
    """
    2-tier voice engine:
      Tier 1 — Gemini TTS (8-key rotating pool × 4 TTS models, studio quality, free)
      Tier 2 — Edge-TTS Neural (free fallback, character-specific voices, micro-varied)
    DSP: 15ms cosine crossfades + 70Hz high-pass filter + soft peak limiter
    """

    def __init__(self):
        self._tts_pool = GeminiTTSPool(GEMINI_TTS_KEYS)

    def _resolve_speaker(self, spk_raw: str, lang: str) -> str:
        key = spk_raw.lower().strip()
        if key in SPEAKER_ALIASES:
            key = SPEAKER_ALIASES[key]
        if key not in VOICE_CONFIGS:
            key = "narrator" if lang == "english" else "stomach"
        return key

    def _synthesize_turn_gemini(self, spec: Dict[str, Any], text: str, output_wav: Path) -> float:
        return self._tts_pool.generate_tts(spec["voice"], spec["style"], text, output_wav)

    async def _synthesize_turn_edge(self, spec: Dict[str, Any], text: str, output_wav: Path, character_key: str = "") -> float:
        import asyncio
        import edge_tts
        varied_rate, varied_pitch = _edge_tts_variation(character_key, spec["rate"], spec["pitch"])
        communicate = edge_tts.Communicate(text, voice=spec["edge_voice"], rate=varied_rate, pitch=varied_pitch)
        mp3_temp = output_wav.with_suffix(".mp3")
        try:
            await asyncio.wait_for(communicate.save(str(mp3_temp)), timeout=10.0)
            await asyncio_to_thread_ffmpeg(mp3_temp, output_wav)
        finally:
            mp3_temp.unlink(missing_ok=True)
        return _probe_duration(output_wav)

    async def generate_dialogue_async(
        self,
        script_lines: List[Dict[str, str]],
        lang: str = "urdu",
        output_prefix: str = "voxstudio_dialogue"
    ) -> Dict[str, Any]:
        import asyncio
        pid_prefix = f"{output_prefix}_{os.getpid()}"
        turn_wavs = []
        turn_durations = []
        all_words = []
        cumulative_ms = 0

        try:
            for idx, item in enumerate(script_lines):
                spk_raw = item.get("speaker", "stomach")
                spk_key = self._resolve_speaker(spk_raw, lang)
                spec = VOICE_CONFIGS[spk_key]
                seg_wav = TEMP_DIR / f"{pid_prefix}_turn_{idx}.wav"

                # Tier 1: Gemini TTS
                try:
                    print(f"    [Gemini TTS – {spec['voice']}] {spk_key.upper()}: '{item['line'][:55]}...'")
                    dur = await asyncio.to_thread(self._synthesize_turn_gemini, spec, item["line"], seg_wav)
                    print(f"       OK — {dur:.2f}s")
                except Exception as e1:
                    print(f"    [Gemini failed: {e1!r}] -> Edge-TTS ({spec['edge_voice']})...")
                    # Tier 2: Edge-TTS
                    dur = await self._synthesize_turn_edge(spec, item["line"], seg_wav, character_key=spk_key)
                    print(f"       OK (Edge-TTS) — {dur:.2f}s")

                turn_wavs.append(seg_wav)
                turn_durations.append(dur + 0.18)

                words = item["line"].split()
                if words:
                    line_dur_ms = int(dur * 1000)
                    weights = []
                    for w in words:
                        clean_tail = w.rstrip("\"'”’)]}")
                        pause_bonus = 0.0
                        if clean_tail.endswith((".", "?", "!")):
                            pause_bonus = 2.5
                        elif clean_tail.endswith((",", ";", ":")):
                            pause_bonus = 1.5
                        weights.append(max(2.0, float(len(w)) + pause_bonus))

                    total_weight = sum(weights) or 1.0
                    running_weight = 0.0
                    for w_i, (w, weight) in enumerate(zip(words, weights)):
                        w_start_rel = int(round(line_dur_ms * (running_weight / total_weight)))
                        running_weight += weight
                        w_end_rel = (
                            line_dur_ms
                            if w_i == len(words) - 1
                            else int(round(line_dur_ms * (running_weight / total_weight)))
                        )
                        all_words.append({
                            "word": w,
                            "speaker": spk_raw,
                            "start_ms": cumulative_ms + w_start_rel,
                            "end_ms": cumulative_ms + max(w_start_rel + 10, w_end_rel),
                        })

                cumulative_ms += int(dur * 1000) + 180

            master_clean_wav = TEMP_DIR / f"{pid_prefix}_clean.wav"
            print("    [DSP] Applying crossfades + high-pass filter...")
            final_total_dur = await asyncio.to_thread(
                stitch_segments_clean,
                segment_paths=turn_wavs,
                output_path=master_clean_wav,
                rate=24000,
                gap_ms=180,
                crossfade_ms=15,
            )
        finally:
            for seg in turn_wavs:
                Path(seg).unlink(missing_ok=True)

        return {
            "audio_path": str(master_clean_wav),
            "words": all_words,
            "line_durations": turn_durations,
            "duration_seconds": final_total_dur
        }


if __name__ == "__main__":
    import asyncio
    vox = VoxStudioEngine()
    test_lines = [
        {"speaker": "stomach", "line": "Arrey Maalik! Raat ke do baje biryani kaun mangwata hai?!"},
        {"speaker": "brain",   "line": "Bhai bas do bite khayenge, chill kar na!"},
    ]
    res = asyncio.run(vox.generate_dialogue_async(test_lines, lang="urdu", output_prefix="test_pool"))
    print("\nMaster Clean Audio:", res["audio_path"])
    print("Duration:          ", res["duration_seconds"])
