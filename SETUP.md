# ClipForge setup

What to install, which API keys to get, and what you need to do so clips come out at commercial-clipper
quality. The lab's **Overview → Setup status** panel (`.venv/bin/python test_lab/run_all.py`) shows live
which of these are done.

## 1. Install (once)

```bash
# FFmpeg with libass — required for captions burned into the video (TikTok/Shorts/Reels ignore soft subtitles)
brew uninstall ffmpeg && brew install ffmpeg-full

# Python deps (project venv)
uv pip install --python .venv/bin/python -e ".[lab]"
```

First runs download models automatically: Whisper large-v3-turbo (~1.6 GB), PANNs audio-event model
(~330 MB, to `~/panns_data`), YuNet face model (230 KB, to `models/`).

## 2. API keys

Copy `.env.example` to `.env` and fill in. Everything is optional — without a key the app uses the
local fallback shown in the table — but the first two are what move quality to industry level.

| Key | Used for | Without it | Cost (approx., verify on the provider's pricing page) |
|---|---|---|---|
| `ASSEMBLYAI_API_KEY` | Captions: Universal-3.5 Pro STT with your context prompt + key terms | Local Whisper large-v3-turbo (~79% word accuracy on music-heavy test video) | ~$0.15–0.26 per audio hour |
| `ANTHROPIC_API_KEY` | Claude picks clips (hook + payoff, self-contained), writes titles/hashtags, proofreads uncertain caption words | Keyword/loudness heuristics pick clips; no proofreading | Claude Opus 5.5: $4 / $20 per M tokens — roughly $0.20–0.50 per 2-hour VOD |
| `TWITCH_CLIENT_ID` + `TWITCH_CLIENT_SECRET` | Import Twitch clip/VOD metadata via the official Helix API | Upload files manually | Free |
| `TWITCH_USER_ACCESS_TOKEN` | Download clips (broadcaster or authorised editor only) | — | Free |
| `YOUTUBE_CLIENT_SECRETS_FILE` | Real YouTube Shorts uploads (Data API v3) | Download the MP4 and upload yourself | Free (10,000 quota units/day) |
| `TIKTOK_ACCESS_TOKEN` | Real TikTok uploads (Content Posting API) | Download the MP4 / export bundle | Free |

Claude calls use the server-side refusal fallback (`fallbacks: "default"`) so a rare declined request is retried
on a suitable model automatically.

### Getting each key

- **AssemblyAI** — sign up at assemblyai.com → Dashboard → API key.
- **Anthropic** — platform.claude.com → API keys (add billing credit).
- **Twitch** — dev.twitch.tv/console → *Register Your Application* (OAuth redirect `http://localhost`) → copy
  Client ID, create a Client Secret. Clip downloads additionally need a *user* token from the broadcaster (or an
  editor) with scope `editor:manage:clips` or `channel:manage:clips` — Twitch does not allow downloading other
  people's clips, and VOD downloads are not offered by the API at all (streamers upload VODs themselves).
- **YouTube** — Google Cloud Console → new project → enable *YouTube Data API v3* → OAuth consent screen (add your
  account as a test user) → Credentials → *OAuth client ID → Desktop app* → download JSON → set its path in
  `YOUTUBE_CLIENT_SECRETS_FILE` → run `.venv/bin/python -m modules.module_10_publishing.youtube_auth` once.
- **TikTok** — developers.tiktok.com → create app → add *Login Kit* and *Content Posting API* (scopes
  `video.upload`, `video.publish`) → complete the OAuth flow for your account → put the user access token in
  `TIKTOK_ACCESS_TOKEN` (tokens expire after ~24 h; refresh tokens last a year).

## 3. Platform approvals (start now — they take weeks)

| Platform | Until approved | Action |
|---|---|---|
| YouTube | API uploads are locked to **private** | Submit the YouTube API Services compliance audit form for your Cloud project |
| TikTok | Posts are **private (SELF_ONLY)**, max 5 users/24 h | Submit the Content Posting API audit in the developer portal |

The publishers enforce these limits. Connections default to `dry_run=True`; set `dry_run=False` on a
`PlatformConnection` (with real credentials) to actually post.

## 4. What you can do for better clips

- **Fill in the context box** (lab sidebar): one sentence about the video plus `Names: …, Terms: …`.
  It is sent to the STT as a prompt and key terms, and to Claude. Names and jargon are the most common caption errors.
- **Balance the stream mix**: background music under speech is the #1 cause of wrong captions (Module 4 reports the
  share — 62% on the ECOSENSE test video). Keep game/music ≥ 10 dB under the mic, or record the mic on its own track.
- **Facecam**: keep the face unobstructed and reasonably lit; corner cams of at least ~150 px tall track reliably.
- **Upload the chat log** for stream VODs (`[HH:MM:SS] user: message` lines or JSON). Chat spikes are a strong
  highlight signal; without a log the scorer relies on audio and transcript only.
- **Hand-label 20–30 highlights** across a few VODs and compare with the candidates the app ranks — that is the
  blueprint's week-2 measurement and the only way to know the selection is actually good for your niche.

## 5. Stack summary

| Stage | Library / API |
|---|---|
| Probe, segment, proxy, render | FFmpeg (libx264 CRF 18 High profile, AAC 48 kHz, two-pass EBU R128 loudnorm to -14 LUFS, libass captions) |
| Speech-to-text | AssemblyAI Universal-3.5 Pro → fallback Whisper large-v3-turbo (mlx-whisper on Apple Silicon / faster-whisper) |
| Caption proofreading, clip selection, titles | Claude (Anthropic API, structured outputs) |
| Audio events | PANNs Cnn14 (AudioSet) — laughter, cheering, screaming, music |
| Scene cuts | PySceneDetect AdaptiveDetector |
| Faces / reframing | OpenCV YuNet + deadband-smoothed 9:16 crop path |
| Twitch | Helix API (Get Clips, Get Clips Download) |
| Publishing | YouTube Data API v3 (google-api-python-client), TikTok Content Posting API |
