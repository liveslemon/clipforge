"""ClipForge Visual Test Studio — Interactive Web Dashboard for testing all 10 modules on local videos."""
from __future__ import annotations

import os
import shutil
import asyncio
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Module Imports
from modules.config import get_settings
from modules.llm import llm_available, LLMError
from modules.module_01_stream_ingest import MediaInspector
from modules.module_02_audio_prep import MediaPreprocessor
from modules.module_03_transcription import (
    AssemblyAIProvider,
    LocalWhisperProvider,
    MockTranscriptionProvider,
    TranscriptAligner,
    SubtitleExporter,
    proofread,
)
from modules.module_04_audio_signals import AcousticAnalyzer
from modules.module_05_chat_analyzer import ChatMessage, ChatVelocityEngine, ChatParser
from modules.module_06_vision_analyzer import FacecamTracker, BoundingBox, SceneDetector
from modules.module_07_highlight_scorer import HighlightScorer, LLMClipSelector, NichePreset
from modules.module_08_video_render import RenderSpec, RenderLayout, CaptionStyle, VideoCompositor
from modules.module_09_rights_engine import RightsManager, PermittedUse
from modules.module_10_publishing import (
    PublisherService,
    PlatformConnection,
    PostMeta,
    Destination,
    PublishPrivacy,
)

app = FastAPI(title="ClipForge Visual Test Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("./studio_uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Shared in-memory active project state
CURRENT_STATE = {
    "video_path": None,
    "metadata": None,
    "prep_result": None,
    "transcript": None,
    "audio_timeline": None,
    "chat_messages": None,
    "candidates": [],
    "rendered_clip_path": None,
}

rights_manager = RightsManager()
publisher_service = PublisherService(rights_manager=rights_manager)


# HTML Frontend
HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ClipForge — Visual Testing Studio</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Plus Jakarta Sans', sans-serif; }
    code, pre { font-family: 'JetBrains Mono', monospace; }
    .tab-active { border-color: #8b5cf6; color: #a78bfa; background-color: rgba(139, 92, 246, 0.1); }
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col antialiased">

  <!-- Header -->
  <header class="border-b border-slate-800 bg-slate-900/60 backdrop-blur sticky top-0 z-50 px-6 py-4 flex items-center justify-between">
    <div class="flex items-center gap-3">
      <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-violet-600 to-indigo-500 flex items-center justify-center font-extrabold text-white shadow-lg shadow-violet-500/20">CF</div>
      <div>
        <h1 class="text-base font-bold text-white tracking-tight flex items-center gap-2">
          ClipForge <span class="text-xs px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-400 border border-violet-500/30 font-medium">Visual Studio</span>
        </h1>
        <p class="text-xs text-slate-400">Interactive testing suite for all 10 platform modules</p>
      </div>
    </div>
    <div class="flex items-center gap-3">
      <button onclick="loadSampleVideo()" class="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition flex items-center gap-1.5 shadow-sm">
        <span>⚡</span> Load Test Sample
      </button>
      <label class="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-violet-600 hover:bg-violet-500 text-white cursor-pointer transition flex items-center gap-1.5 shadow-lg shadow-violet-600/20">
        <span>📁</span> Upload Video From Laptop
        <input type="file" id="videoFileInput" accept="video/*" onchange="uploadLaptopVideo(event)" class="hidden">
      </label>
    </div>
  </header>

  <!-- Main Body -->
  <main class="flex-1 flex overflow-hidden">
    <!-- Left: Video & Current Status -->
    <div class="w-96 border-r border-slate-800 p-5 flex flex-col gap-4 overflow-y-auto bg-slate-900/30">
      <div>
        <h3 class="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Active Video Player</h3>
        <div class="aspect-video bg-black rounded-xl overflow-hidden border border-slate-800 relative flex items-center justify-center">
          <video id="mainVideoPlayer" controls class="w-full h-full object-contain hidden"></video>
          <div id="noVideoPlaceholder" class="text-center p-4">
            <div class="text-3xl mb-2">🎬</div>
            <p class="text-xs text-slate-400">No video loaded yet.<br>Click "Load Test Sample" or upload a file.</p>
          </div>
        </div>
      </div>

      <!-- Quick Metadata Card -->
      <div id="quickMetaCard" class="bg-slate-900 border border-slate-800 rounded-xl p-4 text-xs space-y-2 hidden">
        <div class="font-bold text-slate-200 flex items-center justify-between">
          <span>Active Asset</span>
          <span id="metaDurationBadge" class="bg-violet-500/20 text-violet-300 px-2 py-0.5 rounded text-[11px] font-mono">0.0s</span>
        </div>
        <div class="grid grid-cols-2 gap-2 text-slate-400 font-mono text-[11px] pt-1">
          <div>Resolution: <span id="metaRes" class="text-slate-200 font-semibold">-</span></div>
          <div>FPS: <span id="metaFps" class="text-slate-200 font-semibold">-</span></div>
          <div>Video Codec: <span id="metaVCodec" class="text-slate-200 font-semibold">-</span></div>
          <div>Audio: <span id="metaAudio" class="text-slate-200 font-semibold">-</span></div>
        </div>
        <div class="text-[10px] text-slate-500 truncate font-mono pt-1 border-t border-slate-800/80">SHA: <span id="metaSha">-</span></div>
      </div>

      <!-- One-Click Full Analysis -->
      <button onclick="runFullPipeline()" id="runAllBtn" disabled class="w-full py-2.5 rounded-xl text-xs font-bold bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white shadow-lg shadow-violet-600/25 transition">
        🚀 Run Full Analysis (All Modules)
      </button>

      <!-- Step Status List -->
      <div class="space-y-1.5 text-xs">
        <h4 class="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-1">Module Pipeline Status</h4>
        <div id="statusM1" class="flex items-center justify-between p-2 rounded-lg bg-slate-900 border border-slate-800/60 text-slate-400"><span>1. Stream Ingest</span> <span class="text-slate-600">Pending</span></div>
        <div id="statusM2" class="flex items-center justify-between p-2 rounded-lg bg-slate-900 border border-slate-800/60 text-slate-400"><span>2. Audio & Waveform</span> <span class="text-slate-600">Pending</span></div>
        <div id="statusM3" class="flex items-center justify-between p-2 rounded-lg bg-slate-900 border border-slate-800/60 text-slate-400"><span>3. Speech-to-Text</span> <span class="text-slate-600">Pending</span></div>
        <div id="statusM4" class="flex items-center justify-between p-2 rounded-lg bg-slate-900 border border-slate-800/60 text-slate-400"><span>4. Acoustic Signals</span> <span class="text-slate-600">Pending</span></div>
        <div id="statusM5" class="flex items-center justify-between p-2 rounded-lg bg-slate-900 border border-slate-800/60 text-slate-400"><span>5. Chat Velocity</span> <span class="text-slate-600">Pending</span></div>
        <div id="statusM6" class="flex items-center justify-between p-2 rounded-lg bg-slate-900 border border-slate-800/60 text-slate-400"><span>6. Vision & Facecam</span> <span class="text-slate-600">Pending</span></div>
        <div id="statusM7" class="flex items-center justify-between p-2 rounded-lg bg-slate-900 border border-slate-800/60 text-slate-400"><span>7. Highlight Scoring</span> <span class="text-slate-600">Pending</span></div>
        <div id="statusM8" class="flex items-center justify-between p-2 rounded-lg bg-slate-900 border border-slate-800/60 text-slate-400"><span>8. Video Render</span> <span class="text-slate-600">Pending</span></div>
        <div id="statusM9" class="flex items-center justify-between p-2 rounded-lg bg-slate-900 border border-slate-800/60 text-slate-400"><span>9. Rights Engine</span> <span class="text-slate-600">Pending</span></div>
        <div id="statusM10" class="flex items-center justify-between p-2 rounded-lg bg-slate-900 border border-slate-800/60 text-slate-400"><span>10. Social Publishing</span> <span class="text-slate-600">Pending</span></div>
      </div>
    </div>

    <!-- Right: Tabbed Interactive Inspection Workspace -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <!-- Tabs Navigation -->
      <div class="border-b border-slate-800 bg-slate-900/40 px-5 flex gap-1 overflow-x-auto text-xs font-semibold py-2">
        <button onclick="switchTab('tab1')" id="btnTab1" class="tab-active px-3 py-1.5 rounded-lg border border-transparent transition">M1 Ingest</button>
        <button onclick="switchTab('tab2')" id="btnTab2" class="px-3 py-1.5 rounded-lg border border-transparent text-slate-400 hover:text-slate-200 transition">M2 Waveform</button>
        <button onclick="switchTab('tab3')" id="btnTab3" class="px-3 py-1.5 rounded-lg border border-transparent text-slate-400 hover:text-slate-200 transition">M3 Transcript</button>
        <button onclick="switchTab('tab4')" id="btnTab4" class="px-3 py-1.5 rounded-lg border border-transparent text-slate-400 hover:text-slate-200 transition">M4 Acoustics</button>
        <button onclick="switchTab('tab5')" id="btnTab5" class="px-3 py-1.5 rounded-lg border border-transparent text-slate-400 hover:text-slate-200 transition">M5 Chat</button>
        <button onclick="switchTab('tab6')" id="btnTab6" class="px-3 py-1.5 rounded-lg border border-transparent text-slate-400 hover:text-slate-200 transition">M6 Vision</button>
        <button onclick="switchTab('tab7')" id="btnTab7" class="px-3 py-1.5 rounded-lg border border-transparent text-slate-400 hover:text-slate-200 transition">M7 Highlights</button>
        <button onclick="switchTab('tab8')" id="btnTab8" class="px-3 py-1.5 rounded-lg border border-transparent text-slate-400 hover:text-slate-200 transition">M8 Render</button>
        <button onclick="switchTab('tab9')" id="btnTab9" class="px-3 py-1.5 rounded-lg border border-transparent text-slate-400 hover:text-slate-200 transition">M9 Rights</button>
        <button onclick="switchTab('tab10')" id="btnTab10" class="px-3 py-1.5 rounded-lg border border-transparent text-slate-400 hover:text-slate-200 transition">M10 Publish</button>
      </div>

      <!-- Tab Content Panels -->
      <div class="flex-1 p-6 overflow-y-auto space-y-6">

        <!-- TAB 1: Ingest & Probe -->
        <div id="tab1" class="space-y-4">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-white">Module 1: Stream Ingest & Deep FFprobe Inspector</h2>
            <button onclick="testModule1()" class="px-3 py-1 bg-violet-600 hover:bg-violet-500 text-xs rounded-lg font-semibold">Run Ingest Test</button>
          </div>
          <p class="text-xs text-slate-400 leading-relaxed">Extracts technical container metadata, tracks, codec details, framerate consistency (CFR vs VFR), and computes fast SHA-256 for stream deduplication.</p>
          <pre id="m1Output" class="bg-slate-900 border border-slate-800 rounded-xl p-4 text-xs text-slate-300 overflow-x-auto max-h-96">// Ingest details will appear here...</pre>
        </div>

        <!-- TAB 2: Audio Prep & Waveform -->
        <div id="tab2" class="space-y-4 hidden">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-white">Module 2: Audio Extraction & Waveform Visualizer</h2>
            <button onclick="testModule2()" class="px-3 py-1 bg-violet-600 hover:bg-violet-500 text-xs rounded-lg font-semibold">Generate Waveform</button>
          </div>
          <p class="text-xs text-slate-400">Extracts 16kHz mono audio for STT and downsamples audio amplitude into peak & RMS points for smooth scrubbing.</p>
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-semibold text-slate-300">Scrubber Waveform (Peak & RMS)</span>
              <span id="wfStats" class="text-xs font-mono text-slate-400">-</span>
            </div>
            <canvas id="waveformCanvas" width="800" height="140" class="w-full bg-slate-950 rounded-lg border border-slate-800"></canvas>
          </div>
        </div>

        <!-- TAB 3: Transcript & Boundary Snapping -->
        <div id="tab3" class="space-y-4 hidden">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-white">Module 3: Speech-to-Text & Boundary Snapper</h2>
            <button onclick="testModule3()" class="px-3 py-1 bg-violet-600 hover:bg-violet-500 text-xs rounded-lg font-semibold">Run STT & Snap</button>
          </div>
          <p class="text-xs text-slate-400">Timestamps every spoken word and snaps highlight clip boundaries to sentence starts and natural pauses (silences &ge; 150ms).</p>
          <div id="transcriptContainer" class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3 max-h-96 overflow-y-auto">
            <p class="text-xs text-slate-500 italic">No transcript generated yet.</p>
          </div>
        </div>

        <!-- TAB 4: Acoustic Signals & Energy -->
        <div id="tab4" class="space-y-4 hidden">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-white">Module 4: Acoustic Feature Analyzer (RMS, Pitch & Dead Air)</h2>
            <button onclick="testModule4()" class="px-3 py-1 bg-violet-600 hover:bg-violet-500 text-xs rounded-lg font-semibold">Analyze Acoustics</button>
          </div>
          <p class="text-xs text-slate-400">Computes stream loudness Z-scores ($Z_{RMS}$), pitch variation ($Z_{F0}$), and identifies dead air ($P_{dead}$) stretches.</p>
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-semibold text-slate-300">Acoustic Energy & Z-Score Chart</span>
              <span id="acousticStats" class="text-xs font-mono text-slate-400">-</span>
            </div>
            <canvas id="acousticCanvas" width="800" height="160" class="w-full bg-slate-950 rounded-lg border border-slate-800"></canvas>
            <div class="flex items-center gap-4 text-xs font-mono text-slate-400 mt-2">
              <div class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-amber-400"></span> Z_RMS (Loudness)</div>
              <div class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-cyan-400"></span> Z_Pitch (Frequency)</div>
              <div class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-rose-500"></span> Scream/Laugh Probability</div>
            </div>
          </div>
        </div>

        <!-- TAB 5: Live Stream Chat Velocity -->
        <div id="tab5" class="space-y-4 hidden">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-white">Module 5: Chat Velocity & Reaction Spike Engine</h2>
            <button onclick="testModule5()" class="px-3 py-1 bg-violet-600 hover:bg-violet-500 text-xs rounded-lg font-semibold">Simulate Chat Spikes</button>
          </div>
          <p class="text-xs text-slate-400">Calculates sliding 5-second message rates, detects emote bursts (KEKW, POG), and compensates for 3-8s stream delay.</p>
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <canvas id="chatCanvas" width="800" height="150" class="w-full bg-slate-950 rounded-lg border border-slate-800"></canvas>
            <div id="chatSpikeFeed" class="mt-3 space-y-1.5 max-h-40 overflow-y-auto font-mono text-xs text-slate-300"></div>
          </div>
        </div>

        <!-- TAB 6: Vision & Facecam Tracker -->
        <div id="tab6" class="space-y-4 hidden">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-white">Module 6: Scene Cuts & Deadband Camera Smoothing</h2>
            <button onclick="testModule6()" class="px-3 py-1 bg-violet-600 hover:bg-violet-500 text-xs rounded-lg font-semibold">Test Deadband</button>
          </div>
          <p class="text-xs text-slate-400">Camera crop center remains locked unless face drifts past 25% deadband threshold to prevent micro-jitter, and snaps on OBS scene transitions.</p>
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col md:flex-row gap-4 items-center">
            <div class="relative w-80 h-44 bg-slate-950 border border-slate-800 rounded-lg overflow-hidden flex items-center justify-center" id="deadbandVisualBox">
              <div class="absolute inset-x-1/4 inset-y-1/4 border border-dashed border-violet-500/60 bg-violet-500/5 flex items-center justify-center text-[10px] text-violet-400 font-mono">25% Deadband Zone</div>
              <div id="cameraCenterDot" class="w-3 h-3 rounded-full bg-cyan-400 absolute shadow-lg shadow-cyan-400/50"></div>
              <div id="faceTargetDot" class="w-4 h-4 rounded-full border-2 border-rose-500 absolute"></div>
            </div>
            <div class="flex-1 space-y-2 text-xs">
              <div class="font-semibold text-slate-200">Interactive Jitter Simulation</div>
              <p class="text-slate-400">Move your mouse inside the frame to simulate streamer head movements. Notice the camera center (cyan dot) glides smoothly only when you leave the deadband box!</p>
              <div id="deadbandCoords" class="font-mono text-slate-400 text-[11px]">Center: (960, 540) | Target: (960, 540)</div>
            </div>
          </div>
        </div>

        <!-- TAB 7: Multi-Signal Highlight Scoring -->
        <div id="tab7" class="space-y-4 hidden">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-white">Module 7: Multi-Signal Composite Scorer (C_score)</h2>
            <div class="flex items-center gap-2">
              <select id="nichePresetSelect" class="bg-slate-800 border border-slate-700 text-xs px-2.5 py-1 rounded-lg text-slate-200">
                <option value="GAMING">Gaming Preset</option>
                <option value="JUST_CHATTING">Just Chatting Preset</option>
                <option value="IRL">IRL Stream Preset</option>
                <option value="PODCAST">Podcast Preset</option>
              </select>
              <button onclick="testModule7()" class="px-3 py-1 bg-violet-600 hover:bg-violet-500 text-xs rounded-lg font-semibold">Rank Highlights</button>
            </div>
          </div>
          <p class="text-xs text-slate-400">Combines Transcript Hook ($S_{hook}$), Energy Spikes ($S_{energy}$), Chat Velocity ($S_{chat}$), Narrative ($S_{narrative}$), and Dead-Air ($P_{dead}$).</p>
          <div id="candidatesList" class="space-y-3">
            <p class="text-xs text-slate-500 italic">No candidates generated yet.</p>
          </div>
        </div>

        <!-- TAB 8: Render Compositor -->
        <div id="tab8" class="space-y-4 hidden">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-white">Module 8: 9:16 Vertical Video Compositor & Animated Captions</h2>
            <button onclick="testModule8()" class="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-xs rounded-lg font-semibold">Render Vertical Short</button>
          </div>
          <p class="text-xs text-slate-400">Renders the highlight candidate into an active 9:16 vertical short (1080x1920) with split-screen layout and word-highlight karaoke captions.</p>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <!-- Controls -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3 text-xs">
              <div>
                <label class="block text-slate-400 mb-1 font-semibold">Layout Preset</label>
                <select id="renderLayoutSelect" class="w-full bg-slate-800 border border-slate-700 p-2 rounded-lg text-slate-200">
                  <option value="split">Split Screen (Facecam Top / Gameplay Bottom)</option>
                  <option value="fit">Fit 16:9 with Blurred Background</option>
                  <option value="crop">Center Crop 9:16</option>
                </select>
              </div>
              <div>
                <label class="block text-slate-400 mb-1 font-semibold">Subtitle Style</label>
                <select id="renderStyleSelect" class="w-full bg-slate-800 border border-slate-700 p-2 rounded-lg text-slate-200">
                  <option value="word_highlight">Karaoke Active Word Highlight (Yellow)</option>
                  <option value="bold_pop">Bold Word Pop Animation</option>
                  <option value="clean">Clean Minimalist Subtitles</option>
                </select>
              </div>
              <div id="renderProgressBar" class="hidden space-y-1">
                <div class="text-[11px] text-slate-400 flex justify-between"><span>Compositing FFmpeg...</span> <span id="renderTimer">Processing</span></div>
                <div class="h-2 bg-slate-800 rounded-full overflow-hidden"><div class="h-full bg-emerald-500 animate-pulse w-full"></div></div>
              </div>
            </div>
            <!-- Live Vertical Preview -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col items-center justify-center min-h-[360px]">
              <div class="w-48 aspect-[9/16] bg-black rounded-lg border border-slate-800 overflow-hidden relative shadow-2xl flex items-center justify-center">
                <video id="renderedVerticalPlayer" controls class="w-full h-full object-cover hidden"></video>
                <div id="noRenderPlaceholder" class="text-center p-3">
                  <div class="text-2xl mb-1">📱</div>
                  <p class="text-[11px] text-slate-400">9:16 Vertical Video Output will appear here</p>
                </div>
              </div>
              <a id="downloadRenderBtn" href="#" download="clipforge_vertical_short.mp4" class="mt-3 px-4 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 hidden">
                ⬇ Download Vertical Short
              </a>
            </div>
          </div>
        </div>

        <!-- TAB 9: Rights & Creator Grants -->
        <div id="tab9" class="space-y-4 hidden">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-white">Module 9: Creator Authorization & HMAC Token Engine</h2>
            <button onclick="testModule9()" class="px-3 py-1 bg-violet-600 hover:bg-violet-500 text-xs rounded-lg font-semibold">Generate Invite Token</button>
          </div>
          <p class="text-xs text-slate-400">Creates tamper-proof, 14-day signed tokens for streamers to authorize editors, and verifies strict content rights gates.</p>
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3 text-xs font-mono">
            <div>
              <span class="text-slate-400 font-sans block mb-1">Signed Creator Invite URL:</span>
              <input id="inviteUrlField" readonly class="w-full bg-slate-950 border border-slate-800 p-2.5 rounded-lg text-violet-300 select-all" value="Click Generate to create signed token">
            </div>
            <div id="rightsCheckDisplay" class="p-3 bg-slate-950 rounded-lg border border-slate-800/80 text-slate-300">
              // Permission check results...
            </div>
          </div>
        </div>

        <!-- TAB 10: Social Publishing Simulator -->
        <div id="tab10" class="space-y-4 hidden">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-white">Module 10: Social Publishing & Packaging Adapter</h2>
            <button onclick="testModule10()" class="px-3 py-1 bg-violet-600 hover:bg-violet-500 text-xs rounded-lg font-semibold">Simulate Publish</button>
          </div>
          <p class="text-xs text-slate-400">Checks platform API constraints (YouTube Shorts 180s limits, TikTok audit gating, commercial disclosure), ensures idempotency, and bundles exports.</p>
          <pre id="m10Output" class="bg-slate-900 border border-slate-800 rounded-xl p-4 text-xs text-slate-300 overflow-x-auto max-h-96">// Publishing preflight results will appear here...</pre>
        </div>

      </div>
    </div>
  </main>

  <script>
    let activeTab = 'tab1';
    let currentVideoPath = null;
    let activeCandidates = [];

    function switchTab(tabId) {
      document.querySelectorAll('[id^="tab"]').forEach(el => el.classList.add('hidden'));
      document.querySelectorAll('[id^="btnTab"]').forEach(el => {
        el.classList.remove('tab-active');
        el.classList.add('text-slate-400');
      });
      document.getElementById(tabId).classList.remove('hidden');
      const btnId = 'btn' + tabId.charAt(0).toUpperCase() + tabId.slice(1);
      const btn = document.getElementById(btnId);
      if (btn) {
        btn.classList.add('tab-active');
        btn.classList.remove('text-slate-400');
      }
      activeTab = tabId;
    }

    async function loadSampleVideo() {
      try {
        const res = await fetch('/api/sample');
        const data = await res.json();
        setVideoSource(data.video_path, data.url);
        testModule1();
      } catch (err) {
        alert('Failed to load sample: ' + err);
      }
    }

    async function uploadLaptopVideo(event) {
      const file = event.target.files[0];
      if (!file) return;

      const formData = new FormData();
      formData.append('file', file);

      try {
        const res = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await res.json();
        setVideoSource(data.video_path, data.url);
        testModule1();
      } catch (err) {
        alert('Upload failed: ' + err);
      }
    }

    function setVideoSource(path, url) {
      currentVideoPath = path;
      const player = document.getElementById('mainVideoPlayer');
      const placeholder = document.getElementById('noVideoPlaceholder');
      player.src = url;
      player.classList.remove('hidden');
      placeholder.classList.add('hidden');
      document.getElementById('runAllBtn').disabled = false;
    }

    async function testModule1() {
      const res = await fetch('/api/inspect');
      const data = await res.json();
      document.getElementById('m1Output').textContent = JSON.stringify(data, null, 2);

      // Update quick meta card
      document.getElementById('quickMetaCard').classList.remove('hidden');
      document.getElementById('metaDurationBadge').textContent = data.duration_seconds.toFixed(1) + 's';
      if (data.video_streams && data.video_streams[0]) {
        document.getElementById('metaRes').textContent = data.video_streams[0].width + 'x' + data.video_streams[0].height;
        document.getElementById('metaFps').textContent = data.video_streams[0].fps + ' fps';
        document.getElementById('metaVCodec').textContent = data.video_streams[0].codec_name;
      }
      if (data.audio_streams && data.audio_streams[0]) {
        document.getElementById('metaAudio').textContent = data.audio_streams[0].codec_name + ' ' + (data.audio_streams[0].sample_rate/1000) + 'kHz';
      }
      document.getElementById('metaSha').textContent = (data.sha256_hash || '-').slice(0, 20) + '...';
      document.getElementById('statusM1').innerHTML = '<span>1. Stream Ingest</span> <span class="text-emerald-400 font-bold">✓ Ready</span>';
    }

    async function testModule2() {
      const res = await fetch('/api/prep');
      const data = await res.json();
      document.getElementById('wfStats').textContent = 'Duration: ' + data.duration_s + 's | Points: ' + (data.points ? data.points.length : 0);
      drawWaveform(data.points || []);
      document.getElementById('statusM2').innerHTML = '<span>2. Audio & Waveform</span> <span class="text-emerald-400 font-bold">✓ Ready</span>';
    }

    function drawWaveform(points) {
      const canvas = document.getElementById('waveformCanvas');
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!points.length) return;

      const barWidth = canvas.width / points.length;
      points.forEach((p, i) => {
        const x = i * barWidth;
        const peakHeight = p.peak * (canvas.height / 2);
        const rmsHeight = p.rms * (canvas.height / 2);

        // Peak (violet)
        ctx.fillStyle = '#6366f1';
        ctx.fillRect(x, canvas.height / 2 - peakHeight, barWidth - 1, peakHeight * 2);

        // RMS (bright cyan overlay)
        ctx.fillStyle = '#06b6d4';
        ctx.fillRect(x, canvas.height / 2 - rmsHeight, barWidth - 1, rmsHeight * 2);
      });
    }

    async function testModule3() {
      document.getElementById('statusM3').innerHTML = '<span>3. Speech-to-Text</span> <span class="text-amber-400 font-semibold animate-pulse">⏳ Transcribing…</span>';
      const container = document.getElementById('transcriptContainer');
      container.innerHTML = '<div class="p-6 text-center text-xs text-slate-400"><div class="text-xl mb-2 animate-bounce">🎙️</div><p class="font-semibold text-slate-200 mb-1">Transcribing Speech with AssemblyAI Universal-3.5 Pro</p><p class="text-slate-500">Uploading audio, extracting word-level timestamps & proofreading with OpenAI (usually ~20-35s)…</p></div>';
      const res = await fetch('/api/transcribe');
      const data = await res.json();
      container.innerHTML = '';

      (data.segments || []).forEach(seg => {
        const segDiv = document.createElement('div');
        segDiv.className = 'p-2.5 rounded-lg bg-slate-950 border border-slate-800/80';
        segDiv.innerHTML = `
          <div class="flex justify-between text-[11px] font-mono text-slate-500 mb-1">
            <span>[${(seg.start_ms/1000).toFixed(1)}s -> ${(seg.end_ms/1000).toFixed(1)}s]</span>
            <span class="text-violet-400 font-semibold">${seg.speaker || 'Speaker'}</span>
          </div>
          <p class="text-xs text-slate-200 font-medium">${seg.text}</p>
        `;
        container.appendChild(segDiv);
      });
      document.getElementById('statusM3').innerHTML = '<span>3. Speech-to-Text</span> <span class="text-emerald-400 font-bold">✓ Ready</span>';
    }

    async function testModule4() {
      const res = await fetch('/api/acoustic');
      const data = await res.json();
      document.getElementById('acousticStats').textContent = 'Points: ' + data.points.length;
      drawAcousticChart(data.points);
      document.getElementById('statusM4').innerHTML = '<span>4. Acoustic Signals</span> <span class="text-emerald-400 font-bold">✓ Ready</span>';
    }

    function drawAcousticChart(points) {
      const canvas = document.getElementById('acousticCanvas');
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!points.length) return;

      const step = canvas.width / points.length;

      // Draw Z_RMS (amber)
      ctx.strokeStyle = '#f59e0b';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      points.forEach((p, i) => {
        const y = canvas.height / 2 - (p.z_rms * 15);
        if (i === 0) ctx.moveTo(0, y); else ctx.lineTo(i * step, y);
      });
      ctx.stroke();

      // Draw Scream/Laugh (rose)
      ctx.strokeStyle = '#f43f5e';
      ctx.lineWidth = 2;
      ctx.beginPath();
      points.forEach((p, i) => {
        const y = canvas.height - (p.event_prob * 60);
        if (i === 0) ctx.moveTo(0, y); else ctx.lineTo(i * step, y);
      });
      ctx.stroke();
    }

    async function testModule5() {
      const res = await fetch('/api/chat');
      const data = await res.json();
      const feed = document.getElementById('chatSpikeFeed');
      feed.innerHTML = '<div class="text-slate-400 font-sans font-semibold mb-1">Simulated Chat Stream Events:</div>';
      (data.messages || []).forEach(m => {
        feed.innerHTML += `<div>[${m.timestamp_s.toFixed(1)}s] <span class="text-violet-400 font-semibold">${m.author}</span>: ${m.text}</div>`;
      });
      document.getElementById('statusM5').innerHTML = '<span>5. Chat Velocity</span> <span class="text-emerald-400 font-bold">✓ Ready</span>';
    }

    function testModule6() {
      const box = document.getElementById('deadbandVisualBox');
      const centerDot = document.getElementById('cameraCenterDot');
      const targetDot = document.getElementById('faceTargetDot');
      const coords = document.getElementById('deadbandCoords');

      box.onmousemove = function(e) {
        const rect = box.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        targetDot.style.left = (mouseX - 8) + 'px';
        targetDot.style.top = (mouseY - 8) + 'px';

        // Deadband logic (25% inner box)
        const deadXMin = rect.width * 0.25;
        const deadXMax = rect.width * 0.75;
        const deadYMin = rect.height * 0.25;
        const deadYMax = rect.height * 0.75;

        let cx = parseFloat(centerDot.style.left || (rect.width/2 - 6));
        let cy = parseFloat(centerDot.style.top || (rect.height/2 - 6));

        if (mouseX < deadXMin || mouseX > deadXMax) {
          cx += (mouseX - cx) * 0.15;
        }
        if (mouseY < deadYMin || mouseY > deadYMax) {
          cy += (mouseY - cy) * 0.15;
        }

        centerDot.style.left = cx + 'px';
        centerDot.style.top = cy + 'px';
        coords.textContent = `Center: (${Math.round(cx)}, ${Math.round(cy)}) | Target: (${Math.round(mouseX)}, ${Math.round(mouseY)})`;
      };

      document.getElementById('statusM6').innerHTML = '<span>6. Vision & Facecam</span> <span class="text-emerald-400 font-bold">✓ Ready</span>';
    }

    async function testModule7() {
      const preset = document.getElementById('nichePresetSelect').value;
      const res = await fetch('/api/score?preset=' + preset);
      const data = await res.json();
      activeCandidates = data.candidates || [];
      const list = document.getElementById('candidatesList');
      list.innerHTML = '';

      if (!activeCandidates.length) {
        list.innerHTML = '<p class="text-xs text-slate-500">No highlights detected above threshold.</p>';
        return;
      }

      activeCandidates.forEach((c, idx) => {
        const card = document.createElement('div');
        card.className = 'p-4 rounded-xl bg-slate-900 border border-slate-800 flex items-center justify-between gap-4 hover:border-violet-500/50 transition';
        card.innerHTML = `
          <div class="space-y-1">
            <div class="flex items-center gap-2">
              <span class="text-xs font-bold text-white">#${idx+1} ${c.title}</span>
              <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-violet-500/20 text-violet-300 font-mono">${c.score}/100</span>
            </div>
            <div class="text-[11px] font-mono text-slate-400">[${c.start_s.toFixed(1)}s -> ${c.end_s.toFixed(1)}s] (${c.duration_s}s)</div>
            <p class="text-xs text-slate-300 font-medium">${c.reason}</p>
          </div>
          <button onclick="renderCandidate('${c.id}')" class="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-violet-600 hover:bg-violet-500 text-white shadow transition whitespace-nowrap">
            Render 9:16 Short
          </button>
        `;
        list.appendChild(card);
      });
      document.getElementById('statusM7').innerHTML = '<span>7. Highlight Scoring</span> <span class="text-emerald-400 font-bold">✓ Ready</span>';
    }

    async function renderCandidate(candId) {
      switchTab('tab8');
      testModule8(candId);
    }

    async function testModule8(candId = null) {
      const layout = document.getElementById('renderLayoutSelect').value;
      const style = document.getElementById('renderStyleSelect').value;
      const progress = document.getElementById('renderProgressBar');
      progress.classList.remove('hidden');

      try {
        const res = await fetch(`/api/render?candidate_id=${candId || ''}&layout=${layout}&style=${style}`, { method: 'POST' });
        const data = await res.json();
        progress.classList.add('hidden');

        const player = document.getElementById('renderedVerticalPlayer');
        const placeholder = document.getElementById('noRenderPlaceholder');
        const dlBtn = document.getElementById('downloadRenderBtn');

        player.src = data.url;
        player.classList.remove('hidden');
        placeholder.classList.add('hidden');

        dlBtn.href = data.url;
        dlBtn.classList.remove('hidden');

        document.getElementById('statusM8').innerHTML = '<span>8. Video Render</span> <span class="text-emerald-400 font-bold">✓ 9:16 Rendered</span>';
      } catch (err) {
        alert('Render failed: ' + err);
        progress.classList.add('hidden');
      }
    }

    async function testModule9() {
      const res = await fetch('/api/rights');
      const data = await res.json();
      document.getElementById('inviteUrlField').value = data.invite_url;
      document.getElementById('rightsCheckDisplay').innerHTML = `
        <span class="text-emerald-400 font-bold">Status: ${data.permission_check.allowed ? 'AUTHORIZED' : 'BLOCKED'}</span><br>
        Reason: ${data.permission_check.reason}
      `;
      document.getElementById('statusM9').innerHTML = '<span>9. Rights Engine</span> <span class="text-emerald-400 font-bold">✓ Ready</span>';
    }

    async function testModule10() {
      const res = await fetch('/api/publish');
      const data = await res.json();
      document.getElementById('m10Output').textContent = JSON.stringify(data, null, 2);
      document.getElementById('statusM10').innerHTML = '<span>10. Social Publishing</span> <span class="text-emerald-400 font-bold">✓ Ready</span>';
    }

    async function runFullPipeline() {
      await testModule1();
      await testModule2();
      await testModule3();
      await testModule4();
      await testModule5();
      testModule6();
      await testModule7();
      await testModule9();
      await testModule10();
      alert('Pipeline execution complete across all modules! Switch to M7 or M8 to view and render your clips.');
    }

    // Auto-load sample on start
    window.onload = () => {
      loadSampleVideo();
      testModule6();
    };
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    return HTML_DASHBOARD


@app.get("/api/sample")
async def get_sample():
    demo_file = Path("./demo_output/stream_vod_sample.mp4")
    if not demo_file.exists():
        # Generate sample video if needed
        demo_file.parent.mkdir(parents=True, exist_ok=True)
        import subprocess
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=12:size=1920x1080:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(demo_file),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    CURRENT_STATE["video_path"] = str(demo_file.resolve())
    return {
        "video_path": str(demo_file.resolve()),
        "url": f"/api/files/{demo_file.name}",
    }


@app.post("/api/upload")
async def upload_laptop_video(file: UploadFile = File(...)):
    dest_path = UPLOAD_DIR / file.filename
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    CURRENT_STATE["video_path"] = str(dest_path.resolve())
    return {
        "video_path": str(dest_path.resolve()),
        "url": f"/api/files/{dest_path.name}",
    }


@app.get("/api/inspect")
async def inspect_video():
    vpath = CURRENT_STATE.get("video_path")
    if not vpath or not Path(vpath).exists():
        raise HTTPException(status_code=400, detail="No video loaded.")

    inspector = MediaInspector()
    meta = inspector.inspect(vpath)
    CURRENT_STATE["metadata"] = meta
    return meta.model_dump()


@app.get("/api/prep")
async def prep_audio_and_waveform():
    vpath = CURRENT_STATE.get("video_path")
    if not vpath:
        raise HTTPException(status_code=400, detail="No video loaded.")

    preprocessor = MediaPreprocessor()
    res = preprocessor.process_all(vpath, UPLOAD_DIR, extract_thumbnails_flag=True)
    CURRENT_STATE["prep_result"] = res

    # Read waveform JSON
    import json
    with open(res.waveform_json_path, "r") as f:
        wf_data = json.load(f)

    return wf_data


@app.get("/api/transcribe")
async def transcribe_audio():
    prep_res = CURRENT_STATE.get("prep_result")
    if not prep_res or not Path(prep_res.audio_wav_path).exists():
        raise HTTPException(status_code=400, detail="Audio not prepared yet.")

    wav_path = prep_res.audio_wav_path

    if CURRENT_STATE.get("transcript") and CURRENT_STATE.get("transcript_wav") == wav_path:
        cached = CURRENT_STATE["transcript"]
        res_dict = cached.model_dump()
        res_dict["notes"] = ["Reused existing session transcript."]
        res_dict["corrections"] = []
        return res_dict

    settings = get_settings()

    transcript = None
    notes = []

    # 1. Real Speech-to-Text via AssemblyAI
    if settings.assemblyai_api_key:
        try:
            provider = AssemblyAIProvider(api_key=settings.assemblyai_api_key)
            transcript = await provider.transcribe(wav_path)
            notes.append("Transcribed with AssemblyAI Universal-3.5 Pro.")
        except Exception as e:
            notes.append(f"AssemblyAI failed ({e}), falling back to Whisper...")

    # 2. Local Whisper fallback
    if transcript is None:
        try:
            provider = LocalWhisperProvider()
            transcript = await provider.transcribe(wav_path)
            notes.append("Transcribed with local Whisper.")
        except Exception as e:
            notes.append(f"Local Whisper unavailable ({e}), using mock...")

    # 3. Mock fallback for synthetic test videos
    if transcript is None or not transcript.all_words:
        provider = MockTranscriptionProvider(sample_script=[
            {"speaker": "Streamer", "text": "Wait did you see that incredible shot?!", "start_ms": 1000},
            {"speaker": "Streamer", "text": "Oh my god no way! Clip that right now!", "start_ms": 5000},
            {"speaker": "Streamer", "text": "That was the best clutch of the night.", "start_ms": 8500},
        ])
        transcript = await provider.transcribe(wav_path or "audio.wav")
        notes.append("Used baseline transcript.")

    # 4. Context-aware AI Proofreading via OpenAI / Anthropic
    corrections = []
    proof_status = "skipped"
    if transcript and transcript.all_words and llm_available():
        try:
            transcript, corrections, proof_status = proofread(transcript)
            notes.append(f"AI proofreading: {proof_status}")
        except Exception as e:
            notes.append(f"AI proofreading note: {e}")

    CURRENT_STATE["transcript"] = transcript
    CURRENT_STATE["transcript_wav"] = wav_path
    res_dict = transcript.model_dump()
    res_dict["notes"] = notes
    res_dict["corrections"] = corrections
    return res_dict


@app.get("/api/acoustic")
async def analyze_acoustics():
    prep_res = CURRENT_STATE.get("prep_result")
    if not prep_res or not Path(prep_res.audio_wav_path).exists():
        raise HTTPException(status_code=400, detail="Audio not prepared yet.")

    analyzer = AcousticAnalyzer()
    timeline = analyzer.analyze_wav(prep_res.audio_wav_path)
    CURRENT_STATE["audio_timeline"] = timeline
    return timeline.model_dump()


@app.get("/api/chat")
async def analyze_chat():
    engine = ChatVelocityEngine(lag_compensation_s=4.0)
    messages = [
        ChatMessage(timestamp_s=2.0, author="mod_sam", text="Stream is looking clean!"),
        ChatMessage(timestamp_s=5.2, author="viewer1", text="OMG KEKW CLIP IT", emotes=["kekw"]),
        ChatMessage(timestamp_s=5.6, author="viewer2", text="CLIP IT BRO THAT WAS INSANE KEKW", emotes=["kekw"]),
        ChatMessage(timestamp_s=6.0, author="viewer3", text="POGGERS KEKW", emotes=["pog"]),
        ChatMessage(timestamp_s=6.4, author="viewer4", text="NO WAY KEKW", emotes=["kekw"]),
    ]
    CURRENT_STATE["chat_messages"] = messages
    return {"messages": [m.model_dump() for m in messages]}


@app.get("/api/score")
async def score_highlights(preset: str = "GAMING"):
    transcript = CURRENT_STATE.get("transcript")
    timeline = CURRENT_STATE.get("audio_timeline")
    chat = CURRENT_STATE.get("chat_messages")
    meta = CURRENT_STATE.get("metadata")

    if not transcript or not timeline:
        raise HTTPException(status_code=400, detail="Transcript and acoustics must be computed first.")

    dur = meta.duration_seconds if meta else timeline.duration_s
    # Adaptive clip duration limits
    min_dur = 15.0 if dur >= 40.0 else max(4.0, dur * 0.25)
    max_dur = 60.0 if dur >= 75.0 else min(dur, max(10.0, dur * 0.85))

    candidates = []
    selection_method = ""

    # 1. Industry-Standard LLM Clip Selection (OpenAI gpt-4o-mini)
    if llm_available() and transcript.all_words:
        try:
            selector = LLMClipSelector()
            candidates = selector.select(
                transcript=transcript,
                timeline=timeline,
                chat=chat or [],
                preset=NichePreset(preset),
                min_duration_s=min_dur,
                max_duration_s=max_dur,
                max_candidates=6,
            )
            if candidates:
                llm_name = get_settings().openai_model if get_settings().openai_api_key else "Claude"
                selection_method = f"OpenAI ({llm_name}) + Acoustic/Chat Signals"
        except Exception as e:
            selection_method = f"LLM selector fallback ({e})"

    # 2. Heuristic Multi-Signal Fallback
    if not candidates:
        scorer = HighlightScorer()
        candidates = scorer.find_candidates(
            transcript=transcript,
            audio_timeline=timeline,
            chat_messages=chat,
            preset=NichePreset(preset),
            min_duration_s=min_dur,
            max_duration_s=max_dur,
            stride_s=max(2.0, dur / 15.0),
            max_candidates=6,
        )
        if not selection_method:
            selection_method = "Heuristic Multi-Signal Windows"

    CURRENT_STATE["candidates"] = candidates
    return {
        "candidates": [c.model_dump() for c in candidates],
        "selection_method": selection_method,
        "min_dur": min_dur,
        "max_dur": max_dur,
    }


@app.post("/api/render")
async def render_vertical_short(
    candidate_id: Optional[str] = None,
    layout: str = "split",
    style: str = "word_highlight",
):
    vpath = CURRENT_STATE.get("video_path")
    candidates = CURRENT_STATE.get("candidates", [])
    transcript = CURRENT_STATE.get("transcript")

    if not vpath:
        raise HTTPException(status_code=400, detail="No video loaded.")

    chosen_cand = None
    if candidate_id:
        chosen_cand = next((c for c in candidates if c.id == candidate_id), None)
    if not chosen_cand and candidates:
        chosen_cand = candidates[0]

    in_s = chosen_cand.start_s if chosen_cand else 1.0
    out_s = chosen_cand.end_s if chosen_cand else 8.0

    out_mp4 = UPLOAD_DIR / f"render_{int(in_s)}_{int(out_s)}_{layout}.mp4"

    spec = RenderSpec(
        source_media_path=vpath,
        in_s=in_s,
        out_s=out_s,
        layout=RenderLayout(layout),
        face_region=(1500, 50, 350, 350),
        game_region=(0, 0, 1920, 1080),
    )
    spec.captions.style = CaptionStyle(style)
    spec.captions.enabled = bool(transcript)

    compositor = VideoCompositor()
    words = transcript.all_words if transcript else None
    res = compositor.render(spec, out_mp4, words=words)

    CURRENT_STATE["rendered_clip_path"] = str(out_mp4.resolve())

    return {
        "output_path": str(out_mp4.resolve()),
        "url": f"/api/files/{out_mp4.name}",
        "width": res.width,
        "height": res.height,
        "duration_s": res.duration_s,
    }


@app.get("/api/rights")
async def check_rights_demo():
    token = rights_manager.create_invite_token(
        creator_user_id="creator_shroud",
        channels=["shroud_live"],
        permitted_uses={PermittedUse.EDIT, PermittedUse.DOWNLOAD, PermittedUse.PUBLISH},
        valid_days=14,
    )
    rights_manager.register_owner_attestation("workspace_local", "asset_current", "local_user")
    check = rights_manager.check_permission("workspace_local", "asset_current", PermittedUse.PUBLISH)

    return {
        "invite_url": f"https://app.clipforge.app/claim?token={token}",
        "permission_check": check.model_dump(),
    }


@app.get("/api/publish")
async def publish_demo():
    conn = PlatformConnection(
        id="conn_yt",
        destination=Destination.YOUTUBE_SHORTS,
        account_name="streamer_shorts",
        access_token="simulated_token",
        is_audited=True,
    )
    meta = PostMeta(
        title="Epic Stream Highlight!",
        caption="Scored and clipped automatically with ClipForge.",
        hashtags=["twitch", "gaming", "shorts"],
        privacy=PublishPrivacy.PUBLIC,
    )

    clip_path = CURRENT_STATE.get("rendered_clip_path") or CURRENT_STATE.get("video_path")
    res = await publisher_service.execute_publish(
        workspace_id="workspace_local",
        media_asset_id="asset_current",
        clip_version_id="ver_demo",
        media_path=clip_path or "clip.mp4",
        duration_s=7.0,
        is_vertical=True,
        connection=conn,
        meta=meta,
    )
    return res.model_dump()


@app.get("/api/files/{filename}")
async def serve_file(filename: str):
    # Check UPLOAD_DIR and demo_output
    for directory in [UPLOAD_DIR, Path("./demo_output")]:
        target = directory / filename
        if target.exists():
            return FileResponse(target)
    raise HTTPException(status_code=404, detail="File not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("visual_studio:app", host="127.0.0.1", port=8000, reload=True)
