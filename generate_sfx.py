import os
from pathlib import Path

try:
    import numpy as np
except ImportError:
    import subprocess
    subprocess.run(["pip", "install", "numpy"])
    import numpy as np

import wave

def generate_cinematic_whoosh(filename, duration=1.2, sample_rate=44100):
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    
    # Generate white noise
    noise = np.random.normal(0, 1, len(t))
    
    # Create an envelope: fade in fast, peak, fade out slowly
    # This creates the "whoosh" impact curve
    envelope = (t ** 2) * np.exp(-6 * t)
    # Normalize envelope
    envelope = envelope / np.max(envelope)
    
    # Modulate a low sine wave to give it bass/rumble (a "boom" underneath)
    bass_freq = np.linspace(80, 20, len(t)) # Sweeping down
    bass = np.sin(2 * np.pi * bass_freq * t) * envelope
    
    # Combine noise whoosh + bass boom
    audio = (noise * 0.5 + bass * 0.8) * envelope
    
    # Normalize final audio
    audio = audio / np.max(np.abs(audio))
    
    # Convert to 16-bit PCM
    audio_data = np.int16(audio * 32767)
    
    with wave.open(str(filename), 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data.tobytes())

if __name__ == "__main__":
    sfx_dir = Path("C:/learning/Agents/videos automation/assets/sfx")
    sfx_dir.mkdir(parents=True, exist_ok=True)
    
    # Delete old yt-dlp sfx (which are likely compilations)
    for f in sfx_dir.glob("*.mp3"):
        f.unlink()
    
    # Generate 3 perfect, clean transition whooshes
    generate_cinematic_whoosh(sfx_dir / "clean_whoosh_1.wav", duration=1.2)
    generate_cinematic_whoosh(sfx_dir / "clean_whoosh_2.wav", duration=1.5)
    generate_cinematic_whoosh(sfx_dir / "clean_whoosh_3.wav", duration=0.8)
    
    print("✅ Successfully generated mathematically perfect, clean cinematic whooshes!")
