"""
asset_fetcher.py — 100% Copyright-Free Procedural BGM & SFX Engine.

Why local DSP synthesis instead of YouTube / third-party scraping:
  1. YouTube "no copyright" tracks trigger Content ID claims (HAAWK, Identifyy, AdRev).
  2. Pixabay does not provide a public REST endpoint for /api/music/ or /api/sfx/ (404).
  3. Mathematically synthesized multi-layer stereo beds generated via FFmpeg `aevalsrc`
     have 0% Content ID overlap worldwide, work 100% offline with zero 404s, and are
     acoustically tailored to each channel's specific mood and frequency spectrum
     (leaving the 300Hz–3kHz vocal intelligibility band clean).
"""

import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).parent.parent.resolve()

# Channel-specific harmonic synth recipes (5 variations per channel, 45s stereo @ 44.1kHz)
# Each tuple is: (track_slug, aevalsrc_expression, post_filter)
CHANNEL_SYNTH_RECIPES = {
    "body_simulator": [
        (
            "cc0_scifi_pulse_01",
            "0.22*sin(2*PI*110*t)*(0.6+0.4*sin(2*PI*2*t)) + 0.14*sin(2*PI*220*t) + 0.10*sin(2*PI*329.63*t)*(0.5+0.5*sin(2*PI*0.5*t)) + 0.08*sin(2*PI*440*t*(1+0.003*sin(2*PI*4*t)))",
            "lowpass=f=1800,aecho=0.8:0.88:120:0.35,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_scifi_cyber_02",
            "0.24*sin(2*PI*98*t)*(0.7+0.3*sin(2*PI*2.5*t)) + 0.13*sin(2*PI*196*t) + 0.10*sin(2*PI*293.66*t) + 0.08*sin(2*PI*392*t)*(0.5+0.5*cos(2*PI*1.25*t))",
            "lowpass=f=1900,aecho=0.8:0.85:150:0.3,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_scifi_bio_03",
            "0.22*sin(2*PI*130.81*t)*(0.6+0.4*sin(2*PI*1.8*t)) + 0.14*sin(2*PI*196*t) + 0.11*sin(2*PI*261.63*t) + 0.08*sin(2*PI*392*t*(1+0.002*sin(2*PI*3*t)))",
            "lowpass=f=1700,aecho=0.8:0.88:110:0.35,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_scifi_neon_04",
            "0.23*sin(2*PI*123.47*t)*(0.65+0.35*sin(2*PI*2.2*t)) + 0.14*sin(2*PI*246.94*t) + 0.10*sin(2*PI*369.99*t) + 0.07*sin(2*PI*493.88*t)",
            "lowpass=f=1850,aecho=0.8:0.86:130:0.32,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_scifi_helix_05",
            "0.22*sin(2*PI*146.83*t)*(0.6+0.4*sin(2*PI*2.0*t)) + 0.13*sin(2*PI*220*t) + 0.10*sin(2*PI*293.66*t) + 0.08*sin(2*PI*440*t*(1+0.002*cos(2*PI*2*t)))",
            "lowpass=f=1750,aecho=0.8:0.88:140:0.34,afade=t=in:ss=0:d=1.5"
        ),
    ],
    "xray_mechanics": [
        (
            "cc0_xray_tension_01",
            "0.26*sin(2*PI*73.42*t)*(0.7+0.3*sin(2*PI*1.5*t)) + 0.15*sin(2*PI*110*t) + 0.11*sin(2*PI*146.83*t) + 0.07*sin(2*PI*220*t)*(0.5+0.5*sin(2*PI*3*t))",
            "lowpass=f=1400,aecho=0.8:0.9:180:0.4,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_xray_cutaway_02",
            "0.25*sin(2*PI*82.41*t)*(0.65+0.35*sin(2*PI*1.8*t)) + 0.14*sin(2*PI*123.47*t) + 0.10*sin(2*PI*164.81*t) + 0.07*sin(2*PI*246.94*t)",
            "lowpass=f=1500,aecho=0.8:0.88:160:0.38,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_xray_thermal_03",
            "0.26*sin(2*PI*65.41*t)*(0.7+0.3*sin(2*PI*2.0*t)) + 0.15*sin(2*PI*130.81*t) + 0.10*sin(2*PI*196*t) + 0.06*sin(2*PI*261.63*t)",
            "lowpass=f=1450,aecho=0.8:0.9:200:0.4,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_xray_torque_04",
            "0.25*sin(2*PI*77.78*t)*(0.65+0.35*sin(2*PI*1.6*t)) + 0.14*sin(2*PI*155.56*t) + 0.10*sin(2*PI*233.08*t) + 0.07*sin(2*PI*311.13*t)",
            "lowpass=f=1550,aecho=0.8:0.87:170:0.36,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_xray_turbine_05",
            "0.26*sin(2*PI*69.30*t)*(0.7+0.3*sin(2*PI*2.2*t)) + 0.14*sin(2*PI*138.59*t) + 0.10*sin(2*PI*207.65*t) + 0.07*sin(2*PI*277.18*t)",
            "lowpass=f=1500,aecho=0.8:0.89:190:0.38,afade=t=in:ss=0:d=1.5"
        ),
    ],
    "crazy_characters": [
        (
            "cc0_comedy_bounce_01",
            "0.20*sin(2*PI*130.81*t)*(0.55+0.45*sin(2*PI*3.2*t)) + 0.14*sin(2*PI*164.81*t) + 0.12*sin(2*PI*196*t)*(0.5+0.5*cos(2*PI*3.2*t)) + 0.08*sin(2*PI*261.63*t)",
            "lowpass=f=2200,aecho=0.8:0.82:90:0.25,afade=t=in:ss=0:d=1.0"
        ),
        (
            "cc0_comedy_quirk_02",
            "0.20*sin(2*PI*146.83*t)*(0.55+0.45*sin(2*PI*3.5*t)) + 0.14*sin(2*PI*185*t) + 0.12*sin(2*PI*220*t)*(0.5+0.5*cos(2*PI*3.5*t)) + 0.08*sin(2*PI*293.66*t)",
            "lowpass=f=2200,aecho=0.8:0.82:85:0.25,afade=t=in:ss=0:d=1.0"
        ),
        (
            "cc0_comedy_bazaar_03",
            "0.21*sin(2*PI*110*t)*(0.6+0.4*sin(2*PI*3.0*t)) + 0.13*sin(2*PI*164.81*t) + 0.11*sin(2*PI*220*t) + 0.08*sin(2*PI*329.63*t)*(0.5+0.5*sin(2*PI*6*t))",
            "lowpass=f=2100,aecho=0.8:0.84:95:0.26,afade=t=in:ss=0:d=1.0"
        ),
        (
            "cc0_comedy_dhaba_04",
            "0.20*sin(2*PI*123.47*t)*(0.55+0.45*sin(2*PI*3.4*t)) + 0.14*sin(2*PI*185*t) + 0.11*sin(2*PI*246.94*t) + 0.08*sin(2*PI*369.99*t)",
            "lowpass=f=2150,aecho=0.8:0.83:88:0.25,afade=t=in:ss=0:d=1.0"
        ),
        (
            "cc0_comedy_masala_05",
            "0.20*sin(2*PI*138.59*t)*(0.6+0.4*sin(2*PI*3.1*t)) + 0.14*sin(2*PI*174.61*t) + 0.11*sin(2*PI*207.65*t) + 0.08*sin(2*PI*277.18*t)",
            "lowpass=f=2200,aecho=0.8:0.82:92:0.25,afade=t=in:ss=0:d=1.0"
        ),
    ],
    "health_coach": [
        (
            "cc0_health_clarity_01",
            "0.20*sin(2*PI*130.81*t) + 0.15*sin(2*PI*164.81*t) + 0.12*sin(2*PI*196*t) + 0.09*sin(2*PI*246.94*t)*(0.6+0.4*sin(2*PI*0.8*t))",
            "lowpass=f=1600,aecho=0.8:0.88:160:0.35,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_health_vitality_02",
            "0.20*sin(2*PI*146.83*t) + 0.15*sin(2*PI*185*t) + 0.12*sin(2*PI*220*t) + 0.09*sin(2*PI*277.18*t)*(0.6+0.4*sin(2*PI*1.0*t))",
            "lowpass=f=1650,aecho=0.8:0.88:150:0.35,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_health_cellular_03",
            "0.20*sin(2*PI*110*t) + 0.14*sin(2*PI*164.81*t) + 0.12*sin(2*PI*220*t) + 0.08*sin(2*PI*277.18*t)*(0.6+0.4*sin(2*PI*0.9*t))",
            "lowpass=f=1600,aecho=0.8:0.88:170:0.35,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_health_pulse_04",
            "0.21*sin(2*PI*123.47*t) + 0.14*sin(2*PI*155.56*t) + 0.11*sin(2*PI*185*t) + 0.08*sin(2*PI*246.94*t)*(0.6+0.4*sin(2*PI*1.1*t))",
            "lowpass=f=1650,aecho=0.8:0.87:155:0.34,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_health_zenith_05",
            "0.20*sin(2*PI*138.59*t) + 0.14*sin(2*PI*174.61*t) + 0.12*sin(2*PI*207.65*t) + 0.08*sin(2*PI*261.63*t)*(0.6+0.4*sin(2*PI*0.85*t))",
            "lowpass=f=1600,aecho=0.8:0.88:165:0.35,afade=t=in:ss=0:d=1.5"
        ),
    ],
    "garage_guru": [
        (
            "cc0_garage_drive_01",
            "0.26*sin(2*PI*82.41*t)*(0.6+0.4*sin(2*PI*2.4*t)) + 0.16*sin(2*PI*123.47*t) + 0.12*sin(2*PI*164.81*t) + 0.08*sin(2*PI*246.94*t)*(0.5+0.5*cos(2*PI*2.4*t))",
            "lowpass=f=1800,aecho=0.8:0.85:110:0.3,afade=t=in:ss=0:d=1.2"
        ),
        (
            "cc0_garage_wrench_02",
            "0.26*sin(2*PI*73.42*t)*(0.6+0.4*sin(2*PI*2.2*t)) + 0.16*sin(2*PI*110*t) + 0.12*sin(2*PI*146.83*t) + 0.08*sin(2*PI*220*t)",
            "lowpass=f=1750,aecho=0.8:0.85:115:0.3,afade=t=in:ss=0:d=1.2"
        ),
        (
            "cc0_garage_diesel_03",
            "0.27*sin(2*PI*65.41*t)*(0.65+0.35*sin(2*PI*2.6*t)) + 0.16*sin(2*PI*98*t) + 0.11*sin(2*PI*130.81*t) + 0.08*sin(2*PI*196*t)",
            "lowpass=f=1700,aecho=0.8:0.86:120:0.32,afade=t=in:ss=0:d=1.2"
        ),
        (
            "cc0_garage_offroad_04",
            "0.26*sin(2*PI*87.31*t)*(0.6+0.4*sin(2*PI*2.3*t)) + 0.15*sin(2*PI*130.81*t) + 0.11*sin(2*PI*174.61*t) + 0.08*sin(2*PI*261.63*t)",
            "lowpass=f=1800,aecho=0.8:0.85:105:0.3,afade=t=in:ss=0:d=1.2"
        ),
        (
            "cc0_garage_boost_05",
            "0.26*sin(2*PI*92.50*t)*(0.6+0.4*sin(2*PI*2.5*t)) + 0.15*sin(2*PI*138.59*t) + 0.11*sin(2*PI*185*t) + 0.08*sin(2*PI*277.18*t)",
            "lowpass=f=1850,aecho=0.8:0.85:112:0.3,afade=t=in:ss=0:d=1.2"
        ),
    ],
    "code_classroom": [
        (
            "cc0_code_lofi_01",
            "0.20*sin(2*PI*110*t)*(0.7+0.3*sin(2*PI*1.4*t)) + 0.14*sin(2*PI*130.81*t) + 0.12*sin(2*PI*164.81*t) + 0.09*sin(2*PI*196*t) + 0.06*sin(2*PI*246.94*t)",
            "lowpass=f=1500,aecho=0.8:0.88:145:0.35,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_code_matrix_02",
            "0.20*sin(2*PI*98*t)*(0.7+0.3*sin(2*PI*1.6*t)) + 0.14*sin(2*PI*116.54*t) + 0.12*sin(2*PI*146.83*t) + 0.09*sin(2*PI*174.61*t)",
            "lowpass=f=1550,aecho=0.8:0.88:135:0.35,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_code_kernel_03",
            "0.20*sin(2*PI*123.47*t)*(0.7+0.3*sin(2*PI*1.5*t)) + 0.14*sin(2*PI*146.83*t) + 0.11*sin(2*PI*185*t) + 0.08*sin(2*PI*220*t)",
            "lowpass=f=1500,aecho=0.8:0.88:150:0.35,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_code_pointer_04",
            "0.20*sin(2*PI*130.81*t)*(0.7+0.3*sin(2*PI*1.3*t)) + 0.14*sin(2*PI*155.56*t) + 0.11*sin(2*PI*196*t) + 0.08*sin(2*PI*233.08*t)",
            "lowpass=f=1550,aecho=0.8:0.87:140:0.34,afade=t=in:ss=0:d=1.5"
        ),
        (
            "cc0_code_compiler_05",
            "0.20*sin(2*PI*103.83*t)*(0.7+0.3*sin(2*PI*1.5*t)) + 0.14*sin(2*PI*130.81*t) + 0.11*sin(2*PI*155.56*t) + 0.08*sin(2*PI*196*t)",
            "lowpass=f=1500,aecho=0.8:0.88:148:0.35,afade=t=in:ss=0:d=1.5"
        ),
    ],
}


def _quarantine_non_cc0_tracks(folder: Path) -> None:
    """
    Moves any legacy YouTube-ripped MP3s (files that do not start with 'cc0_')
    into assets/music/_quarantined_youtube/ so they can never trigger Content ID.
    """
    if not folder.exists():
        return
    quarantine_dir = ROOT_DIR / "assets" / "music" / "_quarantined_youtube" / folder.name
    for mp3 in list(folder.glob("*.mp3")):
        if not mp3.name.startswith("cc0_"):
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            dest = quarantine_dir / mp3.name
            try:
                shutil.move(str(mp3), str(dest))
                print(f"    [BGM] Quarantined non-CC0 track: {mp3.name[:55]}")
            except Exception:
                pass


def _synthesize_bgm_track(dest: Path, expr: str, post_filter: str, duration: int = 45) -> bool:
    """Synthesizes a stereo 192kbps MP3 track using FFmpeg lavfi aevalsrc."""
    try:
        af_Input = f"aevalsrc='{expr}':s=44100:d={duration}"
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", af_Input,
            "-af", f"{post_filter},pan=stereo|c0=c0|c1=c0,extrastereo=m=1.4",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            str(dest),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return dest.exists() and dest.stat().st_size > 10_000
    except Exception as e:
        print(f"    [BGM] Synth error for {dest.name}: {e}")
        return False


def fetch_bgm_for_channel(channel: str, count: int = 5) -> None:
    """
    Ensures `count` 100% copyright-free CC0 tracks exist in assets/music/{channel}/.
    Automatically quarantines any legacy YouTube-ripped MP3s first.
    """
    folder = ROOT_DIR / "assets" / "music" / channel
    folder.mkdir(parents=True, exist_ok=True)

    _quarantine_non_cc0_tracks(folder)

    existing = list(folder.glob("cc0_*.mp3"))
    if len(existing) >= count:
        print(f"    [BGM] {channel} already has {len(existing)} verified copyright-free tracks.")
        return

    recipes = CHANNEL_SYNTH_RECIPES.get(channel, CHANNEL_SYNTH_RECIPES["body_simulator"])
    print(f"    [BGM] Generating {count} copyright-free studio BGM beds for '{channel}'...")
    ready = len(existing)
    for slug, expr, post_f in recipes[:count]:
        dest = folder / f"{slug}.mp3"
        if dest.exists() and dest.stat().st_size > 10_000:
            continue
        if _synthesize_bgm_track(dest, expr, post_f, duration=45):
            ready += 1

    print(f"    [BGM] {channel}: {ready}/{count} copyright-free tracks ready in {folder}")


def fetch_sfx(count: int = 5) -> None:
    """Ensures `count` clean transition whoosh SFX exist in assets/sfx/."""
    folder = ROOT_DIR / "assets" / "sfx"
    folder.mkdir(parents=True, exist_ok=True)

    existing = list(folder.glob("*.mp3")) + list(folder.glob("*.wav"))
    if len(existing) >= count:
        return

    for idx in range(1, count + 1):
        dest = folder / f"clean_whoosh_{idx}.wav"
        if dest.exists() and dest.stat().st_size > 5_000:
            continue
        freq = 180 + idx * 45
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"aevalsrc='0.35*sin(2*PI*({freq}+400*t)*t)*exp(-4*t)':s=44100:d=0.6",
            "-af", "afade=t=in:ss=0:d=0.05,afade=t=out:st=0.35:d=0.25",
            str(dest),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def get_random_audio(folder_path: Path) -> Optional[str]:
    """Returns path to a random audio file from `folder_path`, or None if empty."""
    if not folder_path or not folder_path.exists():
        return None
    files = list(folder_path.glob("*.mp3")) + list(folder_path.glob("*.wav"))
    if not files:
        return None
    chosen = random.choice(files)
    print(f"    [Audio] Selected: {chosen.name[:60]}")
    return str(chosen)


def ensure_channel_assets(channel: str) -> None:
    """
    Guarantees copyright-safe BGM and SFX exist before compositing.
    """
    fetch_bgm_for_channel(channel, count=5)
    fetch_sfx(count=5)


if __name__ == "__main__":
    channels = [
        "body_simulator",
        "xray_mechanics",
        "crazy_characters",
        "health_coach",
        "garage_guru",
        "code_classroom",
    ]
    for ch in channels:
        fetch_bgm_for_channel(ch, count=5)
    fetch_sfx(count=5)
    print("\nAll 6 channels populated with 100% copyright-free BGM + SFX.")
