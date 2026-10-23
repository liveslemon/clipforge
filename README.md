# ClipForge — AI Stream & Video Clipping Platform

An end-to-end autonomous pipeline that transforms long-form streams (Twitch, Kick, YouTube) and uploaded videos into viral 9:16 vertical shorts (TikTok, YouTube Shorts, Instagram Reels) using AI transcript analysis, acoustic energy detection, computer vision face tracking, and dynamic animated subtitles.

---

## 🏛 Architecture: 10 Standalone Modules

ClipForge is built as a strictly modular, decoupled system. Each module can be tested, imported, or replaced independently:

| # | Module | Core Functionality | Primary Tech / Model |
|---|---|---|---|
| **01** | `module_01_stream_ingest` | Media probing, deterministic SHA-256 fingerprinting, keyframe-safe chunking | `ffprobe`, `ffmpeg` |
| **02** | `module_02_audio_prep` | 16 kHz mono speech extraction, 100-bin waveform peaks, 720p H.264 proxy | `ffmpeg`, `wave`, `numpy` |
| **03** | `module_03_transcription` | Word-level speech-to-text, sentence alignment, AI domain proofreading, SRT/VTT | AssemblyAI Universal-3.5 Pro, Whisper, OpenAI |
| **04** | `module_04_audio_signals` | 100ms loudness RMS, pitch inflection, shout/laughter/cheer detection | PANNs Cnn14 AudioSet, `scipy`, `librosa` |
| **05** | `module_05_chat_analyzer` | Chat message parsing, velocity spikes, emote tracking, stream delay compensation | Twitch/Kick/YT parsers, `ChatVelocityEngine` |
| **06** | `module_06_vision_analyzer` | Real-time face detection, corner facecam locator, scene cuts, deadband camera smoothing | OpenCV YuNet (`face_detection_yunet`), PySceneDetect |
| **07** | `module_07_highlight_scorer` | LLM clip selection (hook + setup + payoff), composite scoring (0–100), sentence snapping | OpenAI `gpt-4o-mini` / Claude, `HighlightScorer` |
| **08** | `module_08_video_render` | 1080×1920 9:16 vertical short rendering: **Split**, **Crop**, and **Fit** layouts with animated captions | FFmpeg `libass` word-pop karaoke subtitles, EBU R128 `-14 LUFS` loudnorm |
| **09** | `module_09_rights_engine` | Creator permission tokens, signed HMAC verification, attestation ledger | `cryptography`, `hashlib` |
| **10** | `module_10_publishing` | Preflight compliance checks, YouTube Data API v3, TikTok Content Posting API, export bundle | Google API Client, TikTok API, Zip bundler |

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python**: 3.11 or higher
- **FFmpeg**: Must be compiled with `libass` for burned-in animated subtitles.
  - On macOS (Homebrew):
    ```bash
    brew install ffmpeg-full
    ```
  - On Ubuntu/Debian:
    ```bash
    sudo apt-get install ffmpeg libass-dev
    ```

### 2. Installation
Clone the repository and set up a virtual environment:

```bash
git clone <REPO_URL>
cd clipforge

# Using uv (fastest)
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[lab]"

# Or using standard pip
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[lab]"
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Open `.env` and configure your API keys:
- `OPENAI_API_KEY`: Required for LLM clip selection and caption proofreading (`gpt-4o-mini`).
- `ASSEMBLYAI_API_KEY`: Optional but recommended for cloud word-level transcription (Universal-3.5 Pro). If omitted, falls back to local Whisper.
- `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET`: Optional, for direct Twitch stream / clip ingestion.
- `YOUTUBE_CLIENT_SECRETS_FILE`: Optional, for automated direct publishing to YouTube Shorts.

---

## 🖥 Running the Interactive Dashboards

### 🧪 1. ClipForge Test Lab (Recommended for Deep Inspection)
Allows uploading any video and running/debugging each of the 10 modules step-by-step with interactive visual charts, waveforms, facecam deadbands, and rendered 9:16 players.

```bash
uvicorn test_lab.server:app --host 127.0.0.1 --port 8765
```
Open **[http://127.0.0.1:8765](http://127.0.0.1:8765)** in your browser.

### 🎨 2. ClipForge Visual Studio
A streamlined, one-click end-to-end studio for rapid video ingestion, highlight scoring, and vertical rendering:

```bash
uvicorn visual_studio:app --host 127.0.0.1 --port 8000
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

---

## 🧪 Running Unit Tests

All 10 modules have dedicated unit tests with 100% pass rate:

```bash
pytest
```
To run tests for a specific module:
```bash
pytest modules/module_07_highlight_scorer/
```

---

## 🤝 Contributing
1. Create a feature branch: `git checkout -b feature/your-feature-name`
2. Run pytest to ensure all checks pass: `pytest`
3. Commit your changes: `git commit -m "feat: add your feature"`
4. Push to branch: `git push origin feature/your-feature-name`
5. Open a Pull Request on GitHub.
