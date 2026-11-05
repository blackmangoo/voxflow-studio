# 🎬 Autonomous Multi-Channel AI Video Agent

An autonomous, multi-modal generative AI pipeline that creates, scripts, voices, generates, and edits complete, publish-ready 9:16 short-form videos (YouTube Shorts, TikTok, Instagram Reels) across multiple channels with zero human intervention.

Produces synchronized releases in both **Urdu (اردو)** and **English** for every episode.

---

## 🌟 Key Features

- **🧠 Autonomous Director (`brain/`):** 
  - Concept selection with historical deduplication tracking (`autonomous_channel_history.json`).
  - Scene-by-scene cinematic prompt crafting optimized for text-to-video diffusion models.
  - Dual-language screenplay generation (Urdu and English character dialogues).
  - Generation of YouTube/TikTok titles, captions, and hashtags.

- **🎥 Parallel Video Generation Engine (`video_engine/`):**
  - Automates **Google Flow (Omni 1.1 Flash)** using **Playwright**.
  - Multi-account connection pool manager (`FlowPoolManager`) running parallel browser instances.
  - Automatic prompt injection, aspect ratio setting (9:16 vertical), progress monitoring, and CDN MP4 stream interception/download.
  - Built-in mock mode for rapid local testing without consuming AI compute.

- **🎙️ Expressive Voice Acting (`voice/`):**
  - Character persona voice generation with support for **ElevenLabs** and **Edge-TTS**.
  - Native character audio post-processing (pitch shifting, EQ, and pacing per character/organ).
  - Word-level and line-level timestamp generation for synchronization.

- **✨ Dynamic Subtitles (`compositor/modern_subtitles.py`):**
  - Generates animated, high-contrast lower-third `.ass` subtitle files.
  - Language-specific font rendering and styling for both Urdu script and English typography.

- **🎞️ Video Compositor (`compositor/video_editor.py`):**
  - FFmpeg-driven assembly engine.
  - Dynamically aligns scene clip durations to voice acting pacing.
  - Burns styled animated captions directly onto video frames.
  - Exports production-grade 1080x1920 vertical MP4 files with paired metadata files.

---

## 🏗️ Architecture & Pipeline Flow

```
[ User or Cron Trigger ]
           │
           ▼
┌────────────────────────────────────────────────────────┐
│ 1. Brain (MultiChannelDirector)                        │
│    - Deduplicates past episode topics                  │
│    - Writes Urdu & English scripts + Flow prompts      │
└──────────────────────────┬─────────────────────────────┘
                           │
           ┌───────────────┴───────────────┐
           ▼                               ▼
┌─────────────────────────────┐ ┌─────────────────────────────┐
│ 2. Video Engine (Playwright)│ │ 3. Voice Engine             │
│    - Google Flow Automation │ │    - ElevenLabs / Edge-TTS  │
│    - Multi-worker rendering │ │    - Dual Urdu/English tracks│
│    - Intercepts 1080x1920   │ │    - Word timestamp data    │
│      MP4 scene clips        │ └──────────────┬──────────────┘
└──────────┬──────────────────┘                │
           │                                   ▼
           │                    ┌─────────────────────────────┐
           │                    │ 4. Subtitle Generator       │
           │                    │    - Urdu & English .ass    │
           │                    │      animated captions      │
           │                    └──────────────┬──────────────┘
           │                                   │
           └─────────────────┬─────────────────┘
                             ▼
┌────────────────────────────────────────────────────────┐
│ 5. Video Compositor (FFmpeg)                           │
│    - Scene-to-dialogue duration alignment              │
│    - Audio mix + burned subtitle overlays              │
│    - Output: Urdu MP4 + English MP4 + Metadata .txt    │
└────────────────────────────────────────────────────────┘
```

---

## 📁 Directory Structure

```
├── brain/                   # Creative direction, prompts, and dual-language scripting
│   ├── multi_channel_director.py
│   └── autonomous_channel_history.json
├── video_engine/            # Playwright browser automation for Google Flow
│   ├── flow_worker.py
│   └── pool_manager.py
├── voice/                   # Voice synthesis, personas, and pitch processing
│   └── character_voices.py
├── compositor/              # Subtitle rendering and FFmpeg video compositing
│   ├── modern_subtitles.py
│   └── video_editor.py
├── accounts/                # Browser profiles and authentication state
│   └── browser_profiles/
├── output/                  # Final generated videos and metadata
│   ├── body_simulator/      # Channels (Urdu/English subfolders)
│   ├── xray_mechanics/
│   └── crazy_characters/
├── config.py                # Global settings, paths, resolution, voice config
├── multi_channel_agent.py   # Main CLI entry point
├── requirements.txt         # Project dependencies
└── run_daily_episode.bat    # Windows scheduler automation runner
```

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python 3.10+**
- **FFmpeg** installed and accessible in your system `PATH`.
- Playwright browser binaries.

### 2. Installation

1. Clone or navigate to the project directory:
   ```bash
   cd "videos automation"
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/Scripts/activate   # On Windows (Git Bash)
   # or: .\venv\Scripts\activate  # On Windows (PowerShell)
   ```

3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Install Playwright browser dependencies:
   ```bash
   playwright install chromium
   ```

### 3. Configuration

Review `config.py` to customize settings:
- `VOICE_PROVIDER`: Set to `"elevenlabs"` or `"edge-tts"` (free fallback).
- `ELEVENLABS_API_KEY`: Set your ElevenLabs API key if using ElevenLabs.
- `NUM_ACCOUNTS`: Number of parallel Google Flow browser profiles to utilize.

---

## 💻 Usage

### Run Full Autonomous Pipeline

Run generation for a specific channel niche:

```bash
python multi_channel_agent.py --channel body_simulator
```

Available channels:
- `body_simulator`: Medical and human body simulation stories.
- `xray_mechanics`: Mechanical and structural X-ray breakdowns.
- `crazy_characters`: Animated character comedy dialogues.

### Fast Local Testing (Mock Mode)

To test the scripting, audio generation, subtitles, and compositing pipeline without triggering Google Flow browser automation, use `--mock-video`:

```bash
python multi_channel_agent.py --channel body_simulator --mock-video --max-scenes 2
```

---

## 📤 Output Structure

Generated content is automatically organized inside `output/<channel>/`:

```
output/body_simulator/
├── urdu/
│   ├── body_simulator_urdu_concept_timestamp.mp4
│   └── body_simulator_urdu_concept_timestamp.txt    # Title, description, hashtags, script
└── english/
    ├── body_simulator_english_concept_timestamp.mp4
    └── body_simulator_english_concept_timestamp.txt # Title, description, hashtags, script
```

---

## ⏰ Automated Scheduling

For hands-free daily content creation:
- **`setup_scheduler.bat` / `setup_task.ps1`**: Configures a Windows Scheduled Task to run `run_daily_episode.bat`.
- **`run_agent_silent.vbs`**: Triggers batch execution silently in the background without opening a terminal window.
