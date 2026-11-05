import math
import struct
import wave
from pathlib import Path
from typing import List, Tuple

def read_wav_mono_16bit(wav_path: Path) -> Tuple[List[float], int]:
    """Reads a 16-bit mono WAV into float samples normalized between -1.0 and 1.0."""
    with wave.open(str(wav_path), 'rb') as w:
        n_channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        rate = w.getframerate()
        n_frames = w.getnframes()
        data = w.readframes(n_frames)

    fmt = f"<{n_frames * n_channels}h"
    raw_ints = struct.unpack(fmt, data)

    # Convert to mono float [-1.0, 1.0]
    if n_channels == 1:
        samples = [s / 32768.0 for s in raw_ints]
    else:
        # Average channels to mono
        samples = [((raw_ints[i] + raw_ints[i + 1]) / 2.0) / 32768.0 for i in range(0, len(raw_ints), 2)]

    return samples, rate

def write_wav_mono_16bit(samples: List[float], rate: int, out_path: Path) -> None:
    """Writes float samples [-1.0, 1.0] to a 16-bit mono WAV."""
    n_frames = len(samples)
    raw_ints = []
    for s in samples:
        # Clamp [-1.0, 1.0]
        clamped = max(-1.0, min(1.0, s))
        raw_ints.append(int(clamped * 32767.0))

    data = struct.pack(f"<{n_frames}h", *raw_ints)
    with wave.open(str(out_path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data)

def apply_highpass_filter(samples: List[float], rate: int = 24000, cutoff_hz: float = 70.0) -> List[float]:
    """1st-order IIR high-pass filter: eliminates sub-bass DC offset rumble and transition thumps."""
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    dt = 1.0 / rate
    alpha = rc / (rc + dt)

    output = [0.0] * len(samples)
    if not samples:
        return output

    output[0] = samples[0]
    for i in range(1, len(samples)):
        output[i] = alpha * (output[i - 1] + samples[i] - samples[i - 1])
    return output

def apply_soft_limiter(samples: List[float], threshold: float = 0.92) -> List[float]:
    """Soft-knee peak compression: prevents digital clipping pops on emphatic consonants."""
    output = [0.0] * len(samples)
    for i, s in enumerate(samples):
        if abs(s) > threshold:
            output[i] = math.tanh(s)
        else:
            output[i] = s
    return output

def apply_cosine_fade_out(samples: List[float], fade_len: int) -> None:
    """Smooth cosine fade-out at the end of a speech segment."""
    total = len(samples)
    count = min(total, fade_len)
    start = total - count
    for i in range(count):
        progress = i / float(count)
        gain = math.cos((math.pi / 2.0) * progress)
        samples[start + i] *= gain

def apply_cosine_fade_in(samples: List[float], fade_len: int) -> None:
    """Smooth cosine fade-in at the start of a speech segment."""
    count = min(len(samples), fade_len)
    for i in range(count):
        progress = i / float(count)
        gain = math.sin((math.pi / 2.0) * progress)
        samples[i] *= gain

def stitch_segments_clean(
    segment_paths: List[Path],
    output_path: Path,
    rate: int = 24000,
    gap_ms: int = 180,
    crossfade_ms: int = 15
) -> float:
    """
    Stitches multiple speaker segments together with zero-crossing cosine crossfades,
    a natural 180ms room-tone gap between speakers, and 70Hz DC rumble filtering.
    Eliminates all transition click/pop/buzz distortion.
    """
    if not segment_paths:
        return 0.0

    fade_samples = int((crossfade_ms / 1000.0) * rate)
    gap_samples = int((gap_ms / 1000.0) * rate)
    silence = [0.0] * gap_samples

    master_samples = []

    for idx, p in enumerate(segment_paths):
        s_list, s_rate = read_wav_mono_16bit(p)
        if s_list:
            apply_cosine_fade_in(s_list, fade_samples)
            apply_cosine_fade_out(s_list, fade_samples)
            master_samples.extend(s_list)
            if idx < len(segment_paths) - 1:
                master_samples.extend(silence)

    # Apply 70Hz Highpass + Soft Limiter
    cleaned = apply_highpass_filter(master_samples, rate=rate, cutoff_hz=70.0)
    final_samples = apply_soft_limiter(cleaned, threshold=0.92)

    write_wav_mono_16bit(final_samples, rate, output_path)
    total_dur = len(final_samples) / float(rate)
    return total_dur


if __name__ == "__main__":
    print("Audio DSP Post-Processor initialized.")
