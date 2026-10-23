"""ClipForge Test Lab engine: runs each module against a real video and records visual, explainable checks."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import threading
import time
import traceback
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.module_01_stream_ingest import MediaInspector, VideoSegmenter, compute_fast_sha256, detect_platform_and_type
from modules.module_02_audio_prep import MediaPreprocessor, WaveformGenerator
from modules.module_03_transcription import (
    AssemblyAIProvider,
    LocalWhisperProvider,
    MockTranscriptionProvider,
    proofread,
    SubtitleExporter,
    Transcript,
    TranscriptAligner,
)
from modules.config import capability_report, get_settings
from modules.llm import LLMError, llm_available
from modules.module_04_audio_signals import AcousticAnalyzer, AudioEventDetector
from modules.module_05_chat_analyzer import ChatMessage, ChatParser, ChatVelocityEngine
from modules.module_06_vision_analyzer import BoundingBox, FacecamTracker, SceneDetector, YuNetFaceDetector, build_crop_path
from modules.module_07_highlight_scorer import HighlightScorer, LLMClipSelector, NichePreset
from modules.module_08_video_render import CaptionStyle, RenderLayout, RenderSpec, VideoCompositor
from modules.module_09_rights_engine import PermittedUse, RightsError, RightsManager
from modules.module_10_publishing import (
    Destination,
    PlatformConnection,
    PostMeta,
    PublisherService,
    PublishJobState,
    PublishPrivacy,
)

LAB_DIR = Path(__file__).resolve().parent
ROOT = LAB_DIR.parent
RUNS_DIR = LAB_DIR / "runs"
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".flv", ".ts", ".mts", ".3gp"}

MODULES: Dict[int, Dict[str, str]] = {
    1: {"slug": "ingest", "folder": "module_01_stream_ingest", "title": "Stream Ingest & Inspection",
        "blurb": "Reads your file with ffprobe, fingerprints it, and splits it into chunks for parallel processing."},
    2: {"slug": "audio_prep", "folder": "module_02_audio_prep", "title": "Audio Prep & Proxy",
        "blurb": "Extracts 16 kHz mono speech audio, draws the waveform, and builds a browser-friendly 720p proxy + thumbnails."},
    3: {"slug": "transcription", "folder": "module_03_transcription", "title": "Transcription & Alignment",
        "blurb": "Turns speech into word-timed text, finds pauses, snaps clip boundaries to sentences, exports SRT/VTT."},
    4: {"slug": "audio_signals", "folder": "module_04_audio_signals", "title": "Audio Energy Signals",
        "blurb": "Measures loudness, pitch and shout/laugh bursts every 100 ms and scores how 'hype' each window is."},
    5: {"slug": "chat", "folder": "module_05_chat_analyzer", "title": "Chat Velocity",
        "blurb": "Parses chat logs and detects reaction spikes (message rate, emotes, 'clip it') with stream-delay compensation."},
    6: {"slug": "vision", "folder": "module_06_vision_analyzer", "title": "Vision: Scenes & Facecam",
        "blurb": "Finds scene cuts, detects faces, smooths the virtual camera, and classifies the stream layout."},
    7: {"slug": "scorer", "folder": "module_07_highlight_scorer", "title": "Highlight Scorer",
        "blurb": "Combines hook, energy, chat and narrative signals into ranked, sentence-snapped clip candidates."},
    8: {"slug": "render", "folder": "module_08_video_render", "title": "Vertical Render",
        "blurb": "Renders the top candidate as a 1080x1920 short in split, fit and crop layouts with captions."},
    9: {"slug": "rights", "folder": "module_09_rights_engine", "title": "Rights Engine",
        "blurb": "Owner attestation, signed creator invite tokens, permission checks and revocation for this exact file."},
    10: {"slug": "publishing", "folder": "module_10_publishing", "title": "Publishing",
         "blurb": "Platform preflight rules, rights gate, idempotent publishing (simulated APIs) and the local export bundle."},
}


# ----------------------------------------------------------------------------- helpers

_EVENT_DETECTOR = None


def _event_detector() -> AudioEventDetector:
    """PANNs model is ~330 MB; load it once per process."""
    global _EVENT_DETECTOR
    if _EVENT_DETECTOR is None:
        _EVENT_DETECTOR = AudioEventDetector()
    return _EVENT_DETECTOR


class Report:
    """Collects checks for one module run. Status: pass | warn | fail | info."""

    def __init__(self):
        self.checks: List[Dict[str, str]] = []
        self.visuals: Dict[str, Any] = {}

    def add(self, name: str, what: str, status: str, detail: Any = "") -> None:
        self.checks.append({"name": name, "what": what, "status": status, "detail": str(detail)})

    def expect(self, name: str, what: str, ok: bool, detail: Any = "", soft: bool = False) -> bool:
        self.add(name, what, "pass" if ok else ("warn" if soft else "fail"), detail)
        return ok


def ffprobe_json(path: Path) -> Dict[str, Any]:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-print_format", "json", str(path)],
        capture_output=True, text=True,
    )
    return json.loads(res.stdout or "{}")


def stream_of(probe: Dict[str, Any], kind: str) -> Optional[Dict[str, Any]]:
    return next((s for s in probe.get("streams", []) if s.get("codec_type") == kind), None)


def run_async(coro):
    return asyncio.run(coro)


def fmt_t(seconds: float) -> str:
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{s:04.1f}"


def slugify(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")[:40] or "video"


# ----------------------------------------------------------------------------- session

class LabSession:
    """One video under test. Expensive steps are cached so later modules reuse earlier results."""

    def __init__(self, video_path: str | Path, chat_path: Optional[str | Path] = None):
        self.video = Path(video_path).expanduser().resolve()
        if not self.video.is_file():
            raise FileNotFoundError(f"Video not found: {self.video}")
        st = self.video.stat()
        key = hashlib.sha1(f"{self.video}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:8]
        self.run_id = f"{slugify(self.video.stem)}_{key}"
        self.dir = RUNS_DIR / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.chat_path = Path(chat_path).resolve() if chat_path else None
        self.cache: Dict[str, Any] = {}
        self.results: Dict[int, Dict[str, Any]] = {}
        self.progress = ""
        self.lock = threading.RLock()
        self.preset = NichePreset.GAMING
        self.context = ""  # what the video is about + names/terms; steers transcription toward words that fit

    # -- public ---------------------------------------------------------------

    def info(self, full: bool = False) -> Dict[str, Any]:
        proxy = self.dir / "prep" / f"{self.video.stem}_proxy_720p.mp4"
        return {
            "run_id": self.run_id,
            "video_path": str(self.video),
            "video_name": self.video.name,
            "size_mb": round(self.video.stat().st_size / 1e6, 1),
            "chat_path": str(self.chat_path) if self.chat_path else None,
            "context": self.context,
            "proxy": self.rel(proxy) if proxy.exists() else None,
            "results": self.results if full else {n: {"status": r["status"], "counts": r["counts"], "elapsed_s": r["elapsed_s"]}
                                                  for n, r in self.results.items()},
        }

    def set_context(self, context: str) -> None:
        with self.lock:
            self.context = context.strip()
            for k in ("transcript", "candidates", "renders"):
                self.cache.pop(k, None)

    def set_chat(self, chat_path: Optional[Path]) -> None:
        with self.lock:
            self.chat_path = chat_path
            for k in ("chat", "candidates", "renders"):
                self.cache.pop(k, None)

    def run(self, n: int) -> Dict[str, Any]:
        with self.lock:
            t0 = time.time()
            rep = Report()
            try:
                getattr(self, f"_module_{n:02d}")(rep)
            except Exception as e:
                rep.add("Module run crashed", "The module must process this video without raising.", "fail",
                        f"{type(e).__name__}: {e}\n\n{traceback.format_exc(limit=6)}")
            counts = {s: sum(1 for c in rep.checks if c["status"] == s) for s in ("pass", "warn", "fail", "info")}
            status = "fail" if counts["fail"] else ("warn" if counts["warn"] else "pass")
            result = {
                "module": n, **MODULES[n], "status": status, "counts": counts,
                "elapsed_s": round(time.time() - t0, 2), "checks": rep.checks, "visuals": rep.visuals,
                "video": self.info() | {"results": None},
            }
            self.results[n] = result
            self.progress = ""
            (self.dir / "results.json").write_text(json.dumps(self.results, indent=1, default=str))
            return result

    def rel(self, path: str | Path) -> str:
        return Path(path).resolve().relative_to(self.dir).as_posix()

    def step(self, msg: str) -> None:
        self.progress = msg

    # -- cached prerequisites -------------------------------------------------

    def _cached(self, key: str, fn):
        if key not in self.cache:
            self.cache[key] = fn()
        return self.cache[key]

    def meta(self):
        def go():
            self.step("Probing video with ffprobe…")
            return MediaInspector().inspect(self.video)
        return self._cached("meta", go)

    def dims(self):
        """Displayed width/height (after rotation) — what viewers and ffmpeg filters actually see."""
        v = self.meta().primary_video
        return (v.display_width, v.display_height) if v else (1920, 1080)

    def prep(self):
        def go():
            out = self.dir / "prep"
            pre = MediaPreprocessor()
            stem = self.video.stem
            duration = max(1.0, self.meta().duration_seconds)
            thumb_fps = min(0.5, 60.0 / duration)  # at most ~60 thumbnails
            done = {
                "wav": out / f"{stem}_16k_mono.wav",
                "waveform": out / f"{stem}_waveform.json",
                "proxy": out / f"{stem}_proxy_720p.mp4",
                "thumbs": out / "thumbnails",
                "thumb_fps": thumb_fps,
            }
            if (out / ".complete").exists():  # run dir is keyed on path+size+mtime, so this is the same video
                return done
            self.step("Extracting 16 kHz audio + waveform…")
            wav = pre.audio_extractor.extract_stt_audio(self.video, out / f"{stem}_16k_mono.wav")
            WaveformGenerator().generate(wav, out / f"{stem}_waveform.json")
            self.step("Transcoding 720p proxy (long videos take a while)…")
            pre.generate_proxy_video(self.video, out / f"{stem}_proxy_720p.mp4")
            self.step("Extracting thumbnails…")
            shutil.rmtree(done["thumbs"], ignore_errors=True)
            pre.extract_thumbnails(self.video, done["thumbs"], fps=thumb_fps)
            (out / ".complete").touch()
            return done
        return self._cached("prep", go)

    def keyterms(self) -> List[str]:
        """Names/terms from the context box: anything after 'Names:' or 'Terms:', comma-separated."""
        terms: List[str] = []
        for m in re.finditer(r"(?:names?|terms?|keywords?)\s*:\s*([^.\n]+)", self.context, flags=re.I):
            terms += [t.strip() for t in re.split(r"[,;/]", m.group(1)) if t.strip()]
        return terms[:100]

    def transcript(self) -> Dict[str, Any]:
        s = get_settings()
        settings = (f"v3|{'assemblyai' if s.assemblyai_api_key else 'local'}|{os.environ.get('CLIPFORGE_WHISPER_MODEL', '')}"
                    f"|{self.context}|{'proofread' if (s.openai_api_key or s.anthropic_api_key) else ''}")
        cache_file = self.dir / f"transcript_{hashlib.sha1(settings.encode()).hexdigest()[:10]}.json"

        def cached_or_go():
            if cache_file.exists():
                data = json.loads(cache_file.read_text())
                return {**data, "t": Transcript.model_validate(data["t"]),
                        "notes": data["notes"] + [f"Reused cached transcript ({cache_file.name})."]}
            res = go()
            if res["real"]:
                cache_file.write_text(json.dumps({**res, "t": res["t"].model_dump()}, default=str))
            return res

        def go():
            wav = str(self.prep()["wav"])
            notes: List[str] = []
            t = None
            if s.assemblyai_api_key:
                try:
                    self.step("Transcribing with AssemblyAI Universal-3.5 Pro…")
                    t = run_async(AssemblyAIProvider(context=self.context).transcribe(
                        wav, language=None, vocabulary=self.keyterms(), on_progress=self.step))
                except Exception as e:
                    notes.append(f"AssemblyAI failed, fell back to local Whisper: {e}")
            if t is None:
                try:
                    self.step("Transcribing locally with Whisper large-v3-turbo…")
                    t = run_async(LocalWhisperProvider(context=self.context).transcribe(
                        wav, language=None, vocabulary=self.keyterms()))
                except Exception as e:
                    notes.append(f"Local Whisper unavailable: {type(e).__name__}: {e}")
            if t is None:
                # Last resort: mock script spread across the real duration so downstream modules still run
                dur_ms = int(self.meta().duration_seconds * 1000)
                lines = ["Wait did you see that incredible shot?", "Oh my god no way! Clip that right now!",
                         "That was the best clutch of the night.", "Chat, are you seeing this?"]
                script = [{"speaker": "Streamer", "text": txt, "start_ms": int(dur_ms * (i + 0.3) / len(lines))}
                          for i, txt in enumerate(lines)]
                return {"t": run_async(MockTranscriptionProvider(script).transcribe(wav)), "real": False,
                        "notes": notes, "corrections": [], "proofread": "skipped: mock transcript"}
            corrections, proof_status = [], "skipped: no speech"
            if t.all_words:
                self.step("AI is proofreading uncertain caption words…")
                t, corrections, proof_status = proofread(t, self.context)
            return {"t": t, "real": True, "notes": notes, "corrections": corrections, "proofread": proof_status}
        return self._cached("transcript", cached_or_go)

    def timeline(self):
        def go():
            detector, note = None, ""
            try:
                self.step("Loading PANNs audio-event model…")
                detector = _event_detector()
            except Exception as e:
                note = f"PANNs unavailable ({type(e).__name__}: {e}) — using loudness heuristic"
            self.step("Analysing audio energy and events every 100 ms…")
            tl = AcousticAnalyzer().analyze_wav(self.prep()["wav"], event_detector=detector)
            self.cache["event_note"] = note
            return tl
        return self._cached("timeline", go)

    def window_size(self) -> float:
        return float(min(15.0, max(3.0, self.meta().duration_seconds / 12.0)))

    def energy_peaks(self, k: int = 3) -> List[float]:
        """Top-k loudness peaks at least 10 s apart (used to anchor simulated chat)."""
        pts = sorted(self.timeline().points, key=lambda p: p.z_rms, reverse=True)
        peaks: List[float] = []
        gap = min(10.0, self.meta().duration_seconds / 4)
        for p in pts:
            if all(abs(p.timestamp_s - q) >= gap for q in peaks):
                peaks.append(p.timestamp_s)
            if len(peaks) >= k:
                break
        return sorted(peaks)

    def chat(self) -> Dict[str, Any]:
        def go():
            if self.chat_path:
                msgs = ChatParser.from_file(self.chat_path)
                return {"messages": msgs, "simulated": False, "bursts": [], "log": self.chat_path}
            self.step("Simulating chat around audio peaks…")
            rng = random.Random(self.run_id)
            dur = self.meta().duration_seconds
            lag = ChatVelocityEngine().lag_compensation_s
            chatter = ["lol", "this game tho", "hi chat", "W stream", "what rank is this", "gg", "Kappa", "first time here",
                       "nice", "lul", "monkaS", "anyone else lagging"]
            hype = ["CLIP IT", "KEKW", "POG", "NO WAY KEKW", "clip that!!", "OMEGALUL", "POGCHAMP", "W", "INSANE",
                    "clip it bro KEKW"]
            msgs: List[ChatMessage] = []
            t = rng.uniform(0.0, 2.0)
            while t < dur:
                txt = rng.choice(chatter)
                msgs.append(ChatMessage(timestamp_s=round(t, 2), author=f"viewer{rng.randint(1, 400)}", text=txt,
                                        emotes=ChatParser.extract_emotes(txt)))
                t += rng.expovariate(0.5)
            bursts = self.energy_peaks(3)
            for b in bursts:
                for _ in range(rng.randint(14, 22)):
                    ts = b + lag + rng.uniform(-0.5, 3.0)
                    if 0 <= ts <= dur + lag + 3:
                        txt = rng.choice(hype)
                        msgs.append(ChatMessage(timestamp_s=round(ts, 2), author=f"viewer{rng.randint(1, 400)}",
                                                text=txt, emotes=ChatParser.extract_emotes(txt)))
            msgs.sort(key=lambda m: m.timestamp_s)
            log = self.dir / "simulated_chat.txt"
            log.write_text("\n".join(
                f"[{int(m.timestamp_s // 3600):02d}:{int(m.timestamp_s % 3600 // 60):02d}:{m.timestamp_s % 60:05.2f}] "
                f"{m.author}: {m.text}" for m in msgs) + "\n")
            return {"messages": msgs, "simulated": True, "bursts": bursts, "log": log}
        return self._cached("chat", go)

    def vision(self) -> Dict[str, Any]:
        def go():
            prep = self.prep()
            disp_w, disp_h = self.dims()
            detector = SceneDetector()
            self.step(f"Detecting scene cuts ({detector.backend})…")
            cuts = detector.detect_scenes(prep["proxy"])
            faces, face_err = [], None
            try:
                self.step("Tracking faces with YuNet (4 frames/s)…")
                faces = YuNetFaceDetector().track_video(prep["proxy"], sample_fps=4, out_size=(disp_w, disp_h))
            except Exception as e:
                face_err = f"{type(e).__name__}: {e}"
            frames = self._snapshots(prep["proxy"], cuts, faces)
            tracker = FacecamTracker(frame_width=disp_w, frame_height=disp_h)
            tracks = tracker.smooth_face_tracks(faces, scene_cuts=cuts)
            layout, box = tracker.detect_stream_layout(tracks)
            return {"cuts": cuts, "raw": faces, "tracks": tracks, "layout": layout, "box": box, "frames": frames,
                    "face_error": face_err, "scene_backend": detector.backend,
                    "sampled": max(1, int(self.meta().duration_seconds * 4))}
        return self._cached("vision", go)

    def _snapshots(self, proxy: Path, cuts, faces) -> List[Dict[str, Any]]:
        """8 evenly spaced frames with the detected face boxed, plus a frame after each scene cut."""
        import cv2
        frame_dir = self.dir / "vision_frames"
        shutil.rmtree(frame_dir, ignore_errors=True)
        frame_dir.mkdir(parents=True)
        cap = cv2.VideoCapture(str(proxy))
        dur = self.meta().duration_seconds
        disp_w, disp_h = self.dims()
        frames = []
        for i in range(8):
            t = dur * (i + 0.5) / 8
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, img = cap.read()
            if not ok:
                continue
            near = min(faces, key=lambda f: abs(f[0] - t), default=None)
            has_face = near is not None and abs(near[0] - t) <= 0.3
            if has_face:
                sx, sy = img.shape[1] / disp_w, img.shape[0] / disp_h
                b = near[1]
                cv2.rectangle(img, (int(b.x * sx), int(b.y * sy)), (int((b.x + b.width) * sx), int((b.y + b.height) * sy)),
                              (60, 220, 120), 3)
            out = frame_dir / f"frame_{i:02d}.jpg"
            cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            frames.append({"t": round(t, 2), "src": self.rel(out), "face": has_face})
        cut_frames = []
        for c in cuts[:12]:
            cap.set(cv2.CAP_PROP_POS_MSEC, c.timestamp_s * 1000 + 50)
            ok, img = cap.read()
            if ok:
                out = frame_dir / f"cut_{c.scene_index:03d}.jpg"
                cv2.imwrite(str(out), cv2.resize(img, (img.shape[1] * 200 // img.shape[0], 200)))
                cut_frames.append({"t": c.timestamp_s, "score": c.score, "src": self.rel(out)})
        cap.release()
        self.cache["cut_frames"] = cut_frames
        return frames

    def scorer_params(self) -> Dict[str, float]:
        dur = self.meta().duration_seconds
        if dur >= 45:
            return {"min_duration_s": 15.0, "max_duration_s": 60.0, "stride_s": 10.0}
        return {"min_duration_s": round(max(3.0, dur * 0.25), 1), "max_duration_s": round(max(4.0, dur * 0.9), 1),
                "stride_s": round(max(1.0, dur / 10), 1)}

    def candidates(self):
        def go():
            params = self.scorer_params()
            t = self.transcript()["t"]
            chat = self.chat()["messages"]
            if not llm_available():
                reason = "no OPENAI_API_KEY / ANTHROPIC_API_KEY"
            elif not t.all_words:
                reason = "no speech for AI to read"
            else:
                try:
                    self.step("AI is reading the transcript and picking clips…")
                    cands = LLMClipSelector().select(t, self.timeline(), chat, self.preset, params["min_duration_s"],
                                                     params["max_duration_s"], 8, context=self.context)
                    if cands:
                        llm_name = get_settings().openai_model if get_settings().openai_api_key else "Claude"
                        self.cache["selection"] = f"LLM ({llm_name}) + measured signals"
                        return cands
                    reason = "AI's picks did not fit the length limits"
                except LLMError as e:
                    reason = str(e)
            self.cache["selection"] = f"heuristic signals only ({reason})"
            self.step("Scoring highlight windows…")
            return HighlightScorer().find_candidates(transcript=t, audio_timeline=self.timeline(), chat_messages=chat,
                                                     preset=self.preset, max_candidates=8, **params)
        return self._cached("candidates", go)

    def face_region(self):
        disp_w, disp_h = self.dims()
        box = self.vision()["box"]
        if box is None:  # No face found: assume a top-right facecam, scaled to this frame
            w, h = int(disp_w * 0.25), int(disp_h * 0.3)
            return (disp_w - w, 0, w, h), "default top-right region (no face detected)"
        pad_w, pad_h = int(box.width * 0.6), int(box.height * 0.6)
        x, y = max(0, box.x - pad_w), max(0, box.y - pad_h)
        w, h = min(disp_w - x, box.width + 2 * pad_w), min(disp_h - y, box.height + 2 * pad_h)
        return (x, y, w, h), "detected face box (+60% margin)"

    def clip_window(self):
        cands = self.candidates()
        dur = self.meta().duration_seconds
        if cands:
            c = cands[0]
            return c.start_s, min(c.end_s, c.start_s + 30.0, dur), c
        return 0.0, min(8.0, dur), None

    def renders(self) -> Dict[str, Any]:
        def go():
            in_s, out_s, cand = self.clip_window()
            words = self.transcript()["t"].all_words
            face_region, face_src = self.face_region()
            disp_w, disp_h = self.dims()
            vis = self.vision()
            crop_path = build_crop_path(vis["raw"], disp_w, disp_h, in_s, out_s, scene_cuts=vis["cuts"])
            comp = VideoCompositor()
            out = {}
            for layout, style in (("crop", CaptionStyle.WORD_HIGHLIGHT), ("split", CaptionStyle.BOLD_POP),
                                  ("fit", CaptionStyle.WORD_HIGHLIGHT)):
                self.step(f"Rendering {layout} layout ({out_s - in_s:.0f}s clip)…")
                spec = RenderSpec(source_media_path=str(self.video), in_s=in_s, out_s=out_s,
                                  layout=RenderLayout(layout), face_region=face_region,
                                  game_region=(0, 0, disp_w, disp_h),
                                  crop_path=crop_path if layout == "crop" else None)
                spec.captions.style = style
                spec.captions.enabled = bool(words)
                path = self.dir / "renders" / f"short_{layout}.mp4"
                t0 = time.time()
                try:
                    res = comp.render(spec, path, words=words)
                    out[layout] = {"ok": True, "path": path, "res": res, "secs": round(time.time() - t0, 1)}
                except Exception as e:
                    out[layout] = {"ok": False, "error": str(e)[-1500:]}
                # Browser caption track (MP4 soft subs / ASS aren't shown by browsers)
                vtt = self.dir / "renders" / f"short_{layout}.vtt"
                vtt.parent.mkdir(parents=True, exist_ok=True)
                vtt.write_text(clip_vtt(words, in_s, out_s, per_group=spec.captions.words_per_group))
            return {"in_s": in_s, "out_s": out_s, "cand": cand, "face_region": face_region, "face_src": face_src,
                    "burned": comp.has_subtitles_filter, "loudnorm": comp.has_loudnorm, "layouts": out,
                    "crop_path": crop_path}
        return self._cached("renders", go)

    # -- module runners -------------------------------------------------------

    def _module_01(self, rep: Report):
        meta = self.meta()
        probe = ffprobe_json(self.video)
        rep.expect("ffprobe can read the file", "The container is valid media that FFmpeg understands.",
                   bool(probe.get("format")), f"format: {meta.format_name}")
        v = meta.primary_video
        rep.expect("Has a video stream", "Clipping needs pictures; audio-only files are rejected.", v is not None,
                   f"{v.codec_name} {v.width}x{v.height}" if v else "no video stream")
        rep.expect("Duration is readable", "Duration drives every timeline in the pipeline.",
                   meta.duration_seconds > 0, f"{meta.duration_seconds:.2f}s ({fmt_t(meta.duration_seconds)})")
        a = meta.primary_audio
        rep.expect("Has an audio stream", "Transcription and energy scoring need sound. Silent video still runs "
                   "(we generate silence) but highlights will be weak.", a is not None,
                   f"{a.codec_name} {a.sample_rate} Hz, {a.channels} ch" if a else "no audio — silent fallback will be used",
                   soft=True)
        if v:
            disp_w, disp_h = v.display_width, v.display_height
            rep.add("Display size & orientation", "Rotation metadata from phones is applied so portrait footage is "
                    "treated as portrait.", "info",
                    f"coded {v.width}x{v.height}, rotation {v.rotation}°, displayed {disp_w}x{disp_h} "
                    f"({'vertical' if meta.is_vertical else 'horizontal'})")
            rep.expect("Frame rate is sane", "FPS between 1 and 240; anything else means a broken header.",
                       1 <= v.fps <= 240, f"{v.fps} fps")
            rep.expect("Constant frame rate", "Variable frame rate (common on phones/OBS) can drift captions; "
                       "the proxy normalises to 30 fps CFR.", not v.is_vfr,
                       "VFR detected" if v.is_vfr else "CFR", soft=True)
            browser_ok = v.codec_name in ("h264", "vp8", "vp9", "av1")
            rep.add("Browser-playable codec", "Original HEVC/ProRes files may not play in Chrome; the lab previews "
                    "the H.264 proxy from Module 2 instead.", "pass" if browser_ok else "info", v.codec_name)
        self.step("Fingerprinting (fast SHA-256)…")
        h1 = compute_fast_sha256(self.video)
        h2 = compute_fast_sha256(self.video)
        rep.expect("Fingerprint is deterministic", "Hashing first+last 16 MB + size twice gives the same ID "
                   "(used to dedupe uploads).", h1 == h2 == meta.sha256_hash, h1[:16] + "…")

        self.step("Segmenting losslessly into chunks…")
        seg_s = max(2, math.ceil(meta.duration_seconds / 4))
        seg_dir = self.dir / "chunks"
        shutil.rmtree(seg_dir, ignore_errors=True)
        chunks = VideoSegmenter().segment_file(self.video, seg_dir, segment_time_seconds=seg_s)
        total = sum(c.duration_s for c in chunks)
        rep.expect("Segmenter produced chunks", f"Split into ~{seg_s}s pieces with stream copy (no re-encode).",
                   len(chunks) >= 1, f"{len(chunks)} chunks")
        tol = max(1.0, meta.duration_seconds * 0.02)
        rep.expect("Chunks cover the whole video", "Chunk durations should add up to the source duration (cuts "
                   "happen on keyframes so small drift is normal).", abs(total - meta.duration_seconds) <= tol,
                   f"chunks sum {total:.2f}s vs source {meta.duration_seconds:.2f}s")
        rep.visuals["chunks"] = [{"i": c.index, "start": round(c.start_time_s, 2), "dur": round(c.duration_s, 2),
                                  "mb": round(c.size_bytes / 1e6, 2)} for c in chunks]
        shutil.rmtree(seg_dir, ignore_errors=True)  # don't keep a second copy of the video on disk

        urls = ["https://www.twitch.tv/shroud/clip/ReliableGiftedWombat", "https://www.twitch.tv/videos/123456789",
                "https://kick.com/xqc", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", str(self.video)]
        rows = []
        for u in urls:
            try:
                p, m = detect_platform_and_type(u)
                rows.append({"url": u, "platform": p.value, "type": m.value})
            except Exception as e:
                rows.append({"url": u, "platform": "error", "type": str(e)})
        rep.visuals["urls"] = rows
        rep.visuals["meta"] = {
            "File": self.video.name, "Size": f"{meta.file_size_bytes / 1e6:.1f} MB", "Container": meta.format_name,
            "Duration": fmt_t(meta.duration_seconds),
            "Video": f"{v.codec_name}, {v.width}x{v.height}, {v.fps} fps, rot {v.rotation}°" if v else "—",
            "Audio": f"{a.codec_name}, {a.sample_rate} Hz, {a.channels} ch" if a else "none",
            "Vertical": str(meta.is_vertical), "SHA-256 (fast)": meta.sha256_hash,
        }

    def _module_02(self, rep: Report):
        meta = self.meta()
        prep = self.prep()
        with wave.open(str(prep["wav"]), "rb") as wf:
            sr, ch, dur = wf.getframerate(), wf.getnchannels(), wf.getnframes() / float(wf.getframerate())
        rep.expect("Speech WAV is 16 kHz mono", "STT engines and VAD expect 16 kHz / 1 channel / 16-bit PCM.",
                   sr == 16000 and ch == 1, f"{sr} Hz, {ch} ch")
        rep.expect("Audio length matches video", "Audio must line up with the picture or every timestamp drifts.",
                   abs(dur - meta.duration_seconds) <= 0.5, f"wav {dur:.2f}s vs video {meta.duration_seconds:.2f}s")
        if not meta.has_audio:
            rep.add("Silent-video fallback", "Video had no audio track, so a silent WAV was generated.", "warn", "")

        wf_data = json.loads(prep["waveform"].read_text())
        pts = wf_data["points"]
        expected = math.ceil(dur / wf_data["bucket_interval_s"])
        rep.expect("Waveform has one point per 100 ms", "Used to draw the editor's scrub bar.",
                   abs(len(pts) - expected) <= 2, f"{len(pts)} points (expected ≈{expected})")
        rep.expect("Waveform values are normalised", "Every peak/RMS in [0,1] and RMS ≤ peak.",
                   all(0 <= p["rms"] <= p["peak"] + 1e-6 <= 1.0001 for p in pts))
        loudest = max((p["peak"] for p in pts), default=0)
        rep.expect("Audio is not silent", "If peak level is ~0 the mic was muted or the track is empty.",
                   loudest > 0.01, f"max peak {loudest:.3f}", soft=True)

        pp = ffprobe_json(prep["proxy"])
        vs = stream_of(pp, "video") or {}
        p_dur = float(pp.get("format", {}).get("duration", 0))
        num, den = (vs.get("avg_frame_rate") or "0/1").split("/")
        p_fps = float(num) / float(den) if float(den) else 0
        rep.expect("Proxy is ≤720p H.264", "Lightweight preview for smooth scrubbing in the browser.",
                   vs.get("codec_name") == "h264" and int(vs.get("height", 9999)) <= 720,
                   f"{vs.get('codec_name')} {vs.get('width')}x{vs.get('height')}")
        rep.expect("Proxy is browser-safe 8-bit", "yuv420p is required for Chrome/Firefox to play H.264.",
                   vs.get("pix_fmt") == "yuv420p", vs.get("pix_fmt"))
        rep.expect("Proxy is 30 fps CFR", "Constant frame rate keeps captions and cuts frame-accurate.",
                   abs(p_fps - 30) < 0.5, f"{p_fps:.2f} fps")
        rep.expect("Proxy duration matches", "Proxy must be the same length as the source.",
                   abs(p_dur - meta.duration_seconds) <= 0.6, f"{p_dur:.2f}s")
        thumbs = sorted(prep["thumbs"].glob("thumb_*.jpg"))
        exp_thumbs = meta.duration_seconds * prep["thumb_fps"]
        rep.expect("Thumbnails extracted", "Timeline filmstrip frames.", abs(len(thumbs) - exp_thumbs) <= 2,
                   f"{len(thumbs)} thumbnails (expected ≈{exp_thumbs:.0f})")

        step = max(1, len(pts) // 1500)
        rep.visuals["waveform"] = {"t": [p["time_s"] for p in pts[::step]], "peak": [p["peak"] for p in pts[::step]],
                                   "rms": [p["rms"] for p in pts[::step]]}
        rep.visuals["proxy"] = self.rel(prep["proxy"])
        rep.visuals["thumbs"] = [{"src": self.rel(t), "t": round(i / prep["thumb_fps"], 1)} for i, t in enumerate(thumbs)]
        rep.visuals["wav"] = self.rel(prep["wav"])

    def _module_03(self, rep: Report):
        tr = self.transcript()
        t: Transcript = tr["t"]
        for note in tr["notes"]:
            if note.startswith("Reused"):
                rep.add("Cache", "", "info", note)
            else:
                rep.add("Provider fallback", "Tried a real provider first.", "warn", note)
        cloud = t.provider.startswith("assemblyai")
        rep.add("Transcription provider", "Industry standard is a hosted STT (AssemblyAI Universal-3.5 Pro); local "
                "Whisper large-v3-turbo is the offline fallback.",
                "pass" if cloud else ("info" if tr["real"] else "warn"),
                (f"{t.provider}, language={t.language}" + ("" if cloud else " — add ASSEMBLYAI_API_KEY for best accuracy"))
                if tr["real"] else "MOCK transcript — words are NOT from your video")
        words = t.all_words
        md = t.raw_metadata
        rep.add("Topic / names context", "Your description (sidebar) is sent as the STT context prompt and to Claude, "
                "steering unclear words toward ones that fit the video.", "pass" if self.context else "info",
                f"“{self.context}”" + (f" · key terms: {', '.join(self.keyterms())}" if self.keyterms() else "")
                if self.context else "none given — add one for better accuracy on names & jargon")
        if "dropped_hallucinated_segments" in md:
            rep.add("Hallucinations removed", "Stock phrases Whisper invents over music/silence ('Thank you', repeats) "
                    "are dropped when low-confidence.", "info", f"{md['dropped_hallucinated_segments']} segments dropped")
        proof = tr.get("proofread", "")
        rep.add("AI caption proofreading", "LLM reads the whole transcript and fixes ONLY words the speech model "
                "was unsure about, when a similar-sounding phrase clearly fits the context. Timings are kept.",
                "pass" if proof.startswith("ok") else ("warn" if "rejected" in proof or "error" in proof.lower() else "info"),
                proof + ("" if llm_available() else " — add OPENAI_API_KEY to enable"))
        for c in tr.get("corrections", [])[:20]:
            rep.add(f"Fixed at {fmt_t(c['start_s'])}", c["reason"], "info", f"“{c['before']}” → “{c['after']}”")
        low = sum(w.confidence < 0.5 for w in words)
        rep.expect("Word confidence", "Share of words the model was unsure about (dotted in the transcript below). "
                   "High values mean noisy audio / music over speech.", low <= max(3, 0.25 * len(words)),
                   f"{low}/{len(words)} words below 50% confidence", soft=True)
        audio_dur = self.meta().duration_seconds
        rep.expect("Speech detected", "At least one word was recognised.", len(words) > 0,
                   f"{len(words)} words in {len(t.segments)} segments", soft=True)
        mono = all(w.start_ms <= w.end_ms for w in words) and all(
            words[i].start_ms <= words[i + 1].start_ms for i in range(len(words) - 1))
        rep.expect("Word timings are ordered", "Each word starts before it ends, and words are in time order.", mono)
        rep.expect("Words fall inside the audio", "No timestamp past the end of the file.",
                   all(w.end_ms <= audio_dur * 1000 + 1000 for w in words),
                   f"last word ends {words[-1].end_ms / 1000:.2f}s / {audio_dur:.2f}s" if words else "")
        aligner = TranscriptAligner(t)
        pauses = aligner.find_pauses(min_silence_ms=300)
        rep.add("Pauses found", "Silent gaps ≥300 ms between words — natural cut points.", "info", f"{len(pauses)} pauses")

        snaps = []
        snap_ok = True
        for frac in (0.25, 0.5, 0.75):
            target = int(audio_dur * 1000 * frac)
            s = aligner.snap_start_boundary(target, max_lookback_ms=15000)
            e = aligner.snap_end_boundary(target)
            # End lands 300 ms after a word ends (snapping back across a gap is by design) and never mid-word
            # (before the first word has ended there's nothing to snap to, so the target itself is padded)
            end_on_word = (not words or any(w.end_ms + 300 == e for w in words)
                           or (e == target + 300 and not any(w.end_ms <= target for w in words)))
            mid_word = any(w.start_ms < e - 300 < w.end_ms for w in words)
            ok = (target - 15300 <= s <= target) and end_on_word and not mid_word
            snap_ok &= ok
            snaps.append({"target": target / 1000, "start": s / 1000, "end": e / 1000})
        rep.expect("Boundary snapping", "A clip start snaps back (≤15 s) to a sentence start; a clip end never cuts "
                   "inside a word (it lands 300 ms after the nearest word end).", snap_ok, "; ".join(f"{x['target']:.1f}s→start {x['start']:.1f}s / end {x['end']:.1f}s"
                                                         for x in snaps))
        srt = SubtitleExporter.to_srt(t, self.dir / "transcript.srt")
        vtt = SubtitleExporter.to_vtt(t, self.dir / "transcript.vtt")
        js = SubtitleExporter.to_json(t, self.dir / "transcript.json")
        srt_blocks = [b for b in srt.strip().split("\n\n") if b.strip()]
        rep.expect("SRT export is well-formed", "Numbered blocks with 'HH:MM:SS,mmm --> HH:MM:SS,mmm' lines.",
                   all(re.search(r"\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}", b) for b in srt_blocks) if words else True,
                   f"{len(srt_blocks)} caption blocks")
        rep.expect("VTT export is well-formed", "Starts with WEBVTT (browser caption format).", vtt.startswith("WEBVTT"))
        rep.expect("JSON round-trips", "Exported JSON loads back into the same transcript.",
                   len(Transcript.model_validate_json(js).all_words) == len(words))
        rep.visuals.update({
            "words": [{"w": w.word, "s": w.start_ms / 1000, "e": w.end_ms / 1000, "c": w.confidence} for w in words[:4000]],
            "segments": [{"s": s.start_s, "e": s.end_s, "text": s.text} for s in t.segments],
            "pauses": [{"s": p.start_ms / 1000, "e": p.end_ms / 1000} for p in pauses],
            "snaps": snaps, "srt": srt[:4000], "proxy": self.rel(self.prep()["proxy"]), "vtt": self.rel(self.dir / "transcript.vtt"),
            "real": tr["real"], "provider": t.provider,
        })

    def _module_04(self, rep: Report):
        tl = self.timeline()
        dur = self.meta().duration_seconds
        expected = int(dur / tl.interval_s)
        rep.expect("One analysis point per 100 ms", "Timeline resolution used by the scorer.",
                   abs(len(tl.points) - expected) <= 2, f"{len(tl.points)} points (expected ≈{expected})")
        rep.expect("Baselines are finite", "Mean/std of loudness and pitch for this video (the 'normal' level).",
                   all(math.isfinite(x) for x in (tl.baseline_rms_mean, tl.baseline_rms_std, tl.baseline_pitch_mean)),
                   f"RMS μ={tl.baseline_rms_mean:.4f} σ={tl.baseline_rms_std:.4f}, pitch μ={tl.baseline_pitch_mean:.0f} Hz")
        z_mean = sum(p.z_rms for p in tl.points) / max(1, len(tl.points))
        rep.expect("Loudness z-scores are centred", "z = (rms − μ)/σ should average ≈0 for the same video.",
                   abs(z_mean) < 0.1 or tl.baseline_rms_std == 1.0, f"mean z_rms = {z_mean:.3f}")
        rep.expect("Pitch in human voice range", "Pitch is 0 (unvoiced) or 80–600 Hz.",
                   all(p.pitch_hz == 0 or 75 <= p.pitch_hz <= 620 for p in tl.points))
        rep.expect("Event probability in [0,1]", "Shout/laugh/cheer likelihood.", all(0 <= p.event_prob <= 1 for p in tl.points))
        rep.add("Audio-event model", "PANNs (AudioSet-trained CNN) detects laughter, cheering and screaming; the old "
                "fallback guessed from loudness alone.", "pass" if tl.event_source == "panns" else "warn",
                tl.event_source if tl.event_source == "panns" else self.cache.get("event_note", "heuristic"))
        if tl.event_source == "panns":
            rep.add("Reactions detected", "Strongest laughter / cheering / screaming moments (feed the highlight scorer).",
                    "info", ", ".join(f"{p['event']} @{fmt_t(p['t'])} ({p['prob']:.2f})" for p in tl.reaction_peaks[:6])
                    or "none above 30% — no laughter/cheering/screaming in this audio")
            rep.expect("Music under speech", "Share of the audio with music playing. Background music is the #1 cause "
                       "of wrong captions — for streams, lower game/music volume relative to the mic.",
                       tl.music_ratio < 0.4, f"music in {tl.music_ratio:.0%} of the audio", soft=True)
        speech = sum(p.is_speech for p in tl.points) / max(1, len(tl.points))
        rep.expect("Enough sound to analyse", "Share of frames above the speech/noise floor.", speech >= 0.05,
                   f"{speech:.0%} of frames active", soft=True)

        an = AcousticAnalyzer()
        W = self.window_size()
        windows = []
        t = 0.0
        while t < dur - 0.5:
            e = an.evaluate_window(tl, t, min(dur, t + W))
            windows.append({"s": round(t, 2), "e": round(min(dur, t + W), 2), "energy": e.energy_score,
                            "dead": e.dead_air_ratio, "z_rms": e.max_z_rms, "event": e.event_prob})
            t += W
        rep.expect("Window scores in range", f"S_energy and P_dead in [0,1] for every {W:.0f}s window.",
                   all(0 <= w["energy"] <= 1 and 0 <= w["dead"] <= 1 for w in windows), f"{len(windows)} windows")
        if len(windows) >= 2:
            hi = max(windows, key=lambda w: w["z_rms"])
            lo = min(windows, key=lambda w: w["z_rms"])
            rep.expect("Loudest window scores higher", "The window with the biggest loudness spike should beat the "
                       "quietest one on S_energy.", hi["energy"] >= lo["energy"],
                       f"loudest @{fmt_t(hi['s'])}: {hi['energy']:.2f} vs quietest @{fmt_t(lo['s'])}: {lo['energy']:.2f}")
        top = sorted(windows, key=lambda w: w["energy"], reverse=True)[:3]
        rep.add("Most energetic moments", "Where this module thinks the hype is (click the bars to watch).", "info",
                ", ".join(f"{fmt_t(w['s'])} ({w['energy']:.2f})" for w in top))
        step = max(1, len(tl.points) // 1500)
        pts = tl.points[::step]
        rep.visuals.update({
            "t": [p.timestamp_s for p in pts], "rms": [p.rms for p in pts], "z_rms": [p.z_rms for p in pts],
            "pitch": [p.pitch_hz for p in pts], "event": [p.event_prob for p in pts],
            "speech": [1 if p.is_speech else 0 for p in pts], "windows": windows, "proxy": self.rel(self.prep()["proxy"]),
        })

    def _module_05(self, rep: Report):
        ch = self.chat()
        msgs: List[ChatMessage] = ch["messages"]
        engine = ChatVelocityEngine()
        if ch["simulated"]:
            rep.add("Chat source", "Local files have no Twitch chat, so a realistic chat was simulated: background "
                    "chatter + reaction bursts 4.5 s after your 3 loudest moments. Upload a real chat log to test with it.",
                    "warn", f"bursts at {', '.join(fmt_t(b) for b in ch['bursts'])}")
        else:
            rep.add("Chat source", "Your uploaded chat log.", "pass", Path(ch["log"]).name)
        reparsed = ChatParser.from_file(ch["log"])
        if ch["simulated"]:
            same = len(reparsed) == len(msgs) and all(abs(a.timestamp_s - b.timestamp_s) < 0.02 and a.text == b.text
                                                      for a, b in zip(reparsed, msgs))
            rep.expect("Log parser round-trip", "Writing chat as '[HH:MM:SS] user: text' and parsing it back gives "
                       "identical messages.", same, f"{len(reparsed)} / {len(msgs)} messages")
        else:
            rep.expect("Chat log parsed", "Timestamps/author/text extracted from your file.", len(msgs) > 0,
                       f"{len(msgs)} messages")
        with_emote = [m for m in msgs if m.emotes]
        rep.expect("Emotes extracted", "Known emotes (KEKW, POG, LUL…) are pulled out of message text.",
                   len(with_emote) > 0, f"{len(with_emote)} messages contain emotes", soft=True)
        points, mean, std = engine.compute_timeline(msgs)
        rep.expect("Velocity timeline built", "Messages/sec in a 5 s sliding window, every second.", len(points) > 0,
                   f"baseline {mean:.2f} ± {std:.2f} msg/s")
        dur = self.meta().duration_seconds
        W = self.window_size()
        windows = []
        t = 0.0
        while t < dur - 0.5:
            sc = engine.score_window(msgs, t, min(dur, t + W), mean, std)
            windows.append({"s": round(t, 2), "e": round(min(dur, t + W), 2), "score": sc.score, "peak": sc.peak_msg_rate,
                            "clip": sc.has_clip_it_trigger, "emotes": sc.top_emotes})
            t += W
        rep.expect("Scores in [0,1]", "S_chat is normalised.", all(0 <= w["score"] <= 1 for w in windows))
        if windows:
            best = max(windows, key=lambda w: w["score"])
            if ch["simulated"] and ch["bursts"]:
                near = any(best["s"] - W <= b <= best["e"] + W for b in ch["bursts"])
                rep.expect("Spike lands on the reaction", "With 4.5 s lag compensation, the top chat window should "
                           "point at the on-stream moment (not 4.5 s later).", near,
                           f"top window {fmt_t(best['s'])}–{fmt_t(best['e'])} score {best['score']:.2f}")
            else:
                rep.add("Hottest chat window", "", "info", f"{fmt_t(best['s'])}–{fmt_t(best['e'])} score {best['score']:.2f}")
            rep.expect("'Clip it' trigger detected", "Chat asking to clip adds +0.25 to S_chat.",
                       any(w["clip"] for w in windows), soft=True)
        rep.visuals.update({
            "rate_t": [p.timestamp_s for p in points], "rate": [p.msg_rate_per_sec for p in points],
            "emote_rate": [p.emote_rate_per_sec for p in points], "windows": windows, "bursts": ch["bursts"],
            "lag": engine.lag_compensation_s, "simulated": ch["simulated"],
            "messages": [{"t": m.timestamp_s, "a": m.author, "x": m.text, "e": m.emotes} for m in msgs[:400]],
            "proxy": self.rel(self.prep()["proxy"]),
        })

    def _module_06(self, rep: Report):
        vis = self.vision()
        dur = self.meta().duration_seconds
        cuts = vis["cuts"]
        rep.add("Scene detection", "PySceneDetect AdaptiveDetector (industry standard; tolerant of camera motion) — "
                "FFmpeg's scene filter is the fallback.", "pass" if vis["scene_backend"] == "pyscenedetect" else "warn",
                f"{vis['scene_backend']}: {len(cuts)} cuts")
        rep.expect("Cuts are ordered & in range", "Timestamps increase and are inside the video.",
                   all(0 <= c.timestamp_s <= dur + 0.5 for c in cuts) and
                   all(cuts[i].timestamp_s <= cuts[i + 1].timestamp_s for i in range(len(cuts) - 1)))
        rep.expect("Cut scores in [0,1]", "Normalised content-change score of each cut.", all(0 <= c.score <= 1 for c in cuts))
        if vis["face_error"]:
            rep.add("Face detection", "YuNet CNN face detector on 4 frames/s.", "warn", vis["face_error"])
        else:
            rep.add("Face detection", "YuNet CNN face detector (OpenCV) on 4 frames/s — finds small and angled faces the "
                    "old Haar detector missed (green box = face).", "pass" if vis["raw"] else "info",
                    f"faces in {len(vis['raw'])}/{vis['sampled']} sampled frames "
                    f"({len(vis['raw']) / vis['sampled']:.0%})")
        tracks = vis["tracks"]
        if len(tracks) >= 3:
            def jitter(xs):
                return sum(abs(xs[i + 1] - xs[i]) for i in range(len(xs) - 1)) / (len(xs) - 1)
            raw_j = jitter([p.bbox.center_x for p in tracks])
            smooth_j = jitter([p.smoothed_center_x for p in tracks])
            rep.expect("Deadband smoothing reduces jitter", "The virtual camera should move less than the raw face "
                       "box (no shaky crops).", smooth_j <= raw_j + 1e-6, f"raw {raw_j:.1f}px/step → smoothed {smooth_j:.1f}px/step")
        disp_w, disp_h = self.dims()
        box = vis["box"]
        rep.add("Layout classification", "FULL_CAM if the face fills >20% of frame, SPLIT_SCREEN for a corner cam, "
                "FULL_GAMEPLAY if no face.", "info", f"{vis['layout'].value}" + (f" — box {box.x},{box.y} {box.width}x{box.height}" if box else ""))
        if box:
            rep.expect("Facecam box inside frame", "Representative box must fit inside the displayed frame.",
                       box.x >= 0 and box.y >= 0 and box.x + box.width <= disp_w + 2 and box.y + box.height <= disp_h + 2)
        rep.visuals.update({
            "frames": vis["frames"], "cut_frames": self.cache.get("cut_frames", []),
            "cuts": [{"t": c.timestamp_s, "score": c.score} for c in cuts],
            "track_t": [p.timestamp_s for p in tracks], "raw_x": [p.bbox.center_x for p in tracks],
            "smooth_x": [p.smoothed_center_x for p in tracks], "frame_w": disp_w, "frame_h": disp_h,
            "layout": vis["layout"].value, "box": box.model_dump() if box else None,
            "proxy": self.rel(self.prep()["proxy"]), "duration": dur,
        })

    def _module_07(self, rep: Report):
        cands = self.candidates()
        params = self.scorer_params()
        dur = self.meta().duration_seconds
        tr = self.transcript()
        selection = self.cache.get("selection", "")
        rep.add("Clip selection", "Industry standard: an LLM reads the transcript and picks self-contained "
                "clips with a hook and payoff; measured audio/chat signals then re-weight them (60% LLM / 40% signals).",
                "pass" if (selection.startswith("LLM") or selection.startswith("Claude")) else "info",
                selection + ("" if (selection.startswith("LLM") or selection.startswith("Claude")) else " — add OPENAI_API_KEY for LLM selection"))
        rep.add("Inputs", "Signals fed to the scorer.", "info",
                f"preset {self.preset.value}; transcript={'real' if tr['real'] else 'MOCK'}; "
                f"chat={'simulated' if self.chat()['simulated'] else 'uploaded'}; window {params['min_duration_s']}–{params['max_duration_s']}s")
        if not rep.expect("Candidates found", "At least one clip-worthy window survived snapping and ranking.",
                          len(cands) > 0, f"{len(cands)} candidates", soft=True):
            rep.add("Why none?", "Windows are dropped when sentence snapping makes them shorter/longer than the allowed "
                    "range — usually very short videos or no speech.", "info", "")
        rep.expect("Scores in 0–100", "Composite score is a percentage.", all(0 <= c.score <= 100 for c in cands))
        rep.expect("Ranked best-first", "Candidates are sorted by score descending.",
                   all(cands[i].score >= cands[i + 1].score for i in range(len(cands) - 1)))
        rep.expect("Within the video", "Every candidate lies inside the source duration.",
                   all(0 <= c.start_s < c.end_s <= dur + 1 for c in cands))
        rep.expect("Respects length limits", f"Each clip is {params['min_duration_s']}–{params['max_duration_s']}s.",
                   all(params["min_duration_s"] - 0.01 <= c.duration_s <= params["max_duration_s"] + 0.01 for c in cands))
        overlap_ok = True
        for i, a in enumerate(cands):
            for b in cands[i + 1:]:
                ov = max(0, min(a.end_ms, b.end_ms) - max(a.start_ms, b.start_ms))
                if ov / max(1, min(a.end_ms - a.start_ms, b.end_ms - b.start_ms)) > 0.40:
                    overlap_ok = False
        rep.expect("No near-duplicates", "No two candidates overlap by more than 40%.", overlap_ok)
        words = tr["t"].all_words
        inside = [c for c in cands if any(w.start_ms < c.end_ms - 300 < w.end_ms for w in words)]
        rep.expect("Ends don't cut words", "Clip end (minus 300 ms pad) never lands mid-word.", not inside,
                   f"{len(inside)} candidates cut a word" if inside else "")
        rep.expect("Explainable", "Each candidate carries a human-readable reason + component breakdown.",
                   all(c.reason and c.title for c in cands))
        rep.visuals.update({
            "candidates": [{"id": c.id, "s": c.start_s, "e": c.end_s, "score": c.score, "title": c.title,
                            "reason": c.reason, "snippet": c.transcript_snippet, "source": c.source,
                            "hook": c.hook_line, "hashtags": c.hashtags, **c.components.model_dump()}
                           for c in cands],
            "duration": dur, "proxy": self.rel(self.prep()["proxy"]), "preset": self.preset.value,
            "presets": [p.value for p in NichePreset],
        })

    def _module_08(self, rep: Report):
        r = self.renders()
        src_has_audio = self.meta().has_audio
        clip_len = r["out_s"] - r["in_s"]
        rep.add("Clip rendered", "Top candidate from Module 7 (capped at 30 s for the lab).", "info",
                f"{fmt_t(r['in_s'])} → {fmt_t(r['out_s'])} ({clip_len:.1f}s)" +
                (f" — “{r['cand'].title}”" if r["cand"] else " — no candidate, used first seconds"))
        rep.add("Facecam region for split", "Where the top half of the split layout is cropped from.", "info",
                f"{r['face_region']} — {r['face_src']}")
        cp = r["crop_path"]
        disp_w, disp_h = self.dims()
        rep.add("Face-tracked reframe (crop layout)", "The 9:16 window follows the main face with a deadband and easing "
                "(no jitter, snaps on scene cuts) instead of a fixed centre crop.",
                "pass" if cp else "info",
                f"{len(cp)} keyframes, pans across {max(x for _, x in cp) - min(x for _, x in cp):.0f}px" if cp else
                ("source is already vertical — no panning needed" if disp_h > disp_w else "no face found in this clip — centre crop"))
        rep.expect("Loudness normalisation available", "EBU R128 loudnorm to -14 LUFS (TikTok/YouTube/Instagram norm).",
                   r["loudnorm"], "ffmpeg loudnorm filter present" if r["loudnorm"] else "missing — install ffmpeg-full", soft=True)
        rep.expect("Captions burned into video", "Needs FFmpeg built with libass. Without it captions are embedded "
                   "as a soft subtitle track (TikTok/Shorts won't show them). Fix: brew uninstall ffmpeg && brew install ffmpeg-full",
                   r["burned"], "libass available" if r["burned"] else "your ffmpeg has no 'ass'/'subtitles' filter", soft=True)
        out = []
        for layout, info in r["layouts"].items():
            if not info["ok"]:
                rep.add(f"{layout}: render", "FFmpeg render must succeed.", "fail", info["error"])
                continue
            pr = ffprobe_json(info["path"])
            vs, aus = stream_of(pr, "video") or {}, stream_of(pr, "audio")
            d = float(pr.get("format", {}).get("duration", 0))
            rep.expect(f"{layout}: 1080x1920 H.264", "Vertical 9:16 at full HD, yuv420p.",
                       vs.get("width") == 1080 and vs.get("height") == 1920 and vs.get("pix_fmt") == "yuv420p",
                       f"{vs.get('width')}x{vs.get('height')} {vs.get('codec_name')} {vs.get('pix_fmt')}")
            rep.expect(f"{layout}: duration matches clip", "Output length equals in→out.", abs(d - clip_len) <= 0.6,
                       f"{d:.2f}s vs {clip_len:.2f}s (render took {info['secs']}s)")
            rep.expect(f"{layout}: audio kept", "Clip keeps the source audio (AAC 48 kHz).", (aus is not None) or not src_has_audio,
                       f"{aus.get('codec_name')} {aus.get('sample_rate')} Hz" if aus else "no audio")
            if aus is not None and layout == "crop":
                lufs = measure_lufs(info["path"])
                rep.expect("Measured loudness", "Integrated loudness of the rendered clip, measured with FFmpeg's EBU R128 "
                           "meter. Target -14 LUFS ±1.5 (short clips can land a little off with single-pass loudnorm).",
                           lufs is not None and abs(lufs + 14) <= 1.5, f"{lufs:.1f} LUFS" if lufs is not None else "unmeasured",
                           soft=True)
            ass = info["path"].with_name(info["path"].stem + "_captions.ass")
            out.append({"layout": layout, "src": self.rel(info["path"]), "vtt": self.rel(info["path"].with_suffix(".vtt")),
                        "mb": round(info["path"].stat().st_size / 1e6, 2),
                        "ass": ass.read_text()[:3000] if ass.exists() else None})
        if any(o["ass"] for o in out):
            n_lines = out[0]["ass"].count("Dialogue:") if out[0]["ass"] else 0
            rep.add("ASS captions generated", "Word-by-word highlighted caption events for the clip.", "pass",
                    f"{n_lines} caption events (shown in preview via WebVTT)")
        rep.visuals.update({"renders": out, "in_s": r["in_s"], "out_s": r["out_s"]})

    def _module_09(self, rep: Report):
        rm = RightsManager()
        asset = "asset_" + (self.meta().sha256_hash or "x")[:16]
        ws = "ws_lab"
        log = []

        res = rm.check_permission(ws, asset, PermittedUse.PUBLISH)
        log.append(("Check PUBLISH before any rights", res.allowed, res.reason))
        rep.expect("Default deny", "With no rights record, nothing is allowed for this file.", not res.allowed, res.reason)

        rec = rm.register_owner_attestation(ws, asset, "you", permitted_uses={PermittedUse.EDIT, PermittedUse.DOWNLOAD})
        log.append(("Owner attests (EDIT, DOWNLOAD only)", True, rec.id))
        ok_edit = rm.check_permission(ws, asset, PermittedUse.EDIT)
        no_pub = rm.check_permission(ws, asset, PermittedUse.PUBLISH)
        log += [("Check EDIT", ok_edit.allowed, ok_edit.reason), ("Check PUBLISH", no_pub.allowed, no_pub.reason)]
        rep.expect("Attestation grants listed uses", "Owner attestation allows EDIT…", ok_edit.allowed, ok_edit.reason)
        rep.expect("…and nothing more", "…but not PUBLISH, which wasn't attested.", not no_pub.allowed, no_pub.reason)

        token = rm.create_invite_token("creator_lab", ["my_channel"], {PermittedUse.EDIT, PermittedUse.PUBLISH}, valid_days=14)
        grant = rm.claim_invite_token(token, "ws_editor")
        rights = rm.grant_rights_to_media(grant.id, asset)
        ed_pub = rm.check_permission("ws_editor", asset, PermittedUse.PUBLISH)
        log += [("Creator signs invite → editor claims", True, grant.id), ("Editor PUBLISH", ed_pub.allowed, ed_pub.reason)]
        rep.expect("Invite token flow", "Creator-signed token lets the editor's workspace publish this file.",
                   ed_pub.allowed, ed_pub.reason)
        other = rm.check_permission("ws_stranger", asset, PermittedUse.PUBLISH)
        rep.expect("Other workspaces denied", "Rights are scoped to the workspace that claimed them.", not other.allowed, other.reason)

        payload, sig = token.split(".")
        tampered = payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB") + "." + sig
        try:
            rm.claim_invite_token(tampered, "ws_attacker")
            tamper_blocked, msg = False, "accepted!"
        except RightsError as e:
            tamper_blocked, msg = True, str(e)
        log.append(("Tampered token claim", not tamper_blocked, msg))
        rep.expect("Tampered token rejected", "Changing any byte breaks the HMAC signature.", tamper_blocked, msg)

        rm.revoke_rights(rights.id)
        after = rm.check_permission("ws_editor", asset, PermittedUse.PUBLISH)
        log.append(("Creator revokes → editor PUBLISH", after.allowed, after.reason))
        rep.expect("Revocation is immediate", "After revoke, the editor can no longer publish.", not after.allowed, after.reason)
        rep.visuals["log"] = [{"step": s, "allowed": a, "detail": d} for s, a, d in log]
        rep.visuals["asset"] = asset
        rep.visuals["token"] = token[:48] + "…"

    def _module_10(self, rep: Report):
        r = self.renders()
        clip = next((v for k, v in r["layouts"].items() if v["ok"]), None)
        if not clip:
            rep.add("Rendered clip available", "Publishing needs a rendered short from Module 8.", "fail", "all renders failed")
            return
        path = clip["path"]
        pr = ffprobe_json(path)
        vs = stream_of(pr, "video") or {}
        dur = float(pr["format"]["duration"])
        vertical = int(vs.get("height", 0)) > int(vs.get("width", 0))
        cand = r["cand"]
        meta = PostMeta(title=(cand.title if cand else self.video.stem)[:90],
                        caption=(cand.hook_line if cand and cand.hook_line else "Clipped with ClipForge."),
                        hashtags=(cand.hashtags if cand and cand.hashtags else ["clipforge", "shorts"]))
        st = get_settings()
        live = [name for name, ok in (("YouTube", bool(st.youtube_client_secrets_file and Path(st.youtube_client_secrets_file).exists())),
                                      ("TikTok", bool(st.tiktok_access_token))) if ok]
        rep.add("Real platform credentials", "The lab always runs publishers in dry-run (nothing is posted). Real uploads "
                "use the YouTube Data API v3 and TikTok Content Posting API once credentials are configured.",
                "pass" if live else "info", ("configured: " + ", ".join(live)) if live else
                "none configured — see SETUP.md (YouTube OAuth client, TikTok access token)")
        rm = RightsManager()
        svc = PublisherService(rights_manager=rm)
        asset = "asset_" + (self.meta().sha256_hash or "x")[:16]
        rows = []

        def conn(dest, audited):
            return PlatformConnection(id=f"c_{dest.value}_{audited}", destination=dest, account_name="lab",
                                      access_token="simulated", is_audited=audited)

        yt, tt = svc.publishers[Destination.YOUTUBE_SHORTS], svc.publishers[Destination.TIKTOK]
        pf = run_async(yt.preflight(conn(Destination.YOUTUBE_SHORTS, True), str(path), dur, vertical))
        rows.append({"step": "YouTube preflight (audited)", "ok": pf.eligible, "detail": "; ".join(pf.warnings) or "eligible"})
        rep.expect("YouTube Shorts eligible", "≤180 s and vertical → can be a Short.", pf.eligible and vertical,
                   f"{dur:.1f}s, vertical={vertical}")
        pf2 = run_async(yt.preflight(conn(Destination.YOUTUBE_SHORTS, False), str(path), dur, vertical))
        rows.append({"step": "YouTube preflight (unaudited app)", "ok": pf2.eligible, "detail": f"forced {pf2.forced_privacy}"})
        rep.expect("Unaudited YouTube → private", "Google locks unaudited API uploads to private.",
                   pf2.forced_privacy == PublishPrivacy.PRIVATE)
        pf3 = run_async(tt.preflight(conn(Destination.TIKTOK, False), str(path), dur, vertical))
        rows.append({"step": "TikTok preflight (unaudited app)", "ok": pf3.eligible, "detail": f"forced {pf3.forced_privacy}"})
        rep.expect("TikTok length rule", "TikTok needs 3 s–10 min.", (3 <= dur <= 600) == pf3.eligible, f"{dur:.1f}s")
        rep.expect("Unaudited TikTok → inbox draft", "Unaudited TikTok apps can only post private drafts.",
                   pf3.forced_privacy == PublishPrivacy.INBOX_DRAFT or not pf3.eligible)

        c_yt = conn(Destination.YOUTUBE_SHORTS, True)
        denied = run_async(svc.execute_publish(workspace_id="ws_lab", media_asset_id=asset, clip_version_id="v1",
                                               media_path=str(path), duration_s=dur, is_vertical=vertical,
                                               connection=c_yt, meta=meta))
        rows.append({"step": "Publish without rights", "ok": denied.status == PublishJobState.PUBLISHED,
                     "detail": denied.error_message})
        rep.expect("Rights gate blocks publishing", "No PUBLISH right → job fails before calling the platform.",
                   denied.status == PublishJobState.FAILED, denied.error_message)
        rm.register_owner_attestation("ws_lab", asset, "you")
        first = run_async(svc.execute_publish(workspace_id="ws_lab", media_asset_id=asset, clip_version_id="v1",
                                              media_path=str(path), duration_s=dur, is_vertical=vertical,
                                              connection=c_yt, meta=meta))
        second = run_async(svc.execute_publish(workspace_id="ws_lab", media_asset_id=asset, clip_version_id="v1",
                                               media_path=str(path), duration_s=dur, is_vertical=vertical,
                                               connection=c_yt, meta=meta))
        rows.append({"step": "Publish with owner attestation (simulated API)", "ok": first.status == PublishJobState.PUBLISHED,
                     "detail": first.post_url or first.error_message})
        rows.append({"step": "Publish again (same clip/account)", "ok": second.external_post_id == first.external_post_id,
                     "detail": f"same post id: {second.external_post_id}"})
        rep.expect("Publishes once rights exist", "Simulated YouTube API call succeeds.",
                   first.status == PublishJobState.PUBLISHED, first.post_url or first.error_message)
        rep.expect("Idempotent retries", "Re-publishing the same clip version to the same account returns the "
                   "existing post instead of double-posting.", second.external_post_id == first.external_post_id,
                   f"key {first.idempotency_key}")

        local = run_async(svc.execute_publish(workspace_id="ws_lab", media_asset_id=asset, clip_version_id="v1",
                                              media_path=str(path), duration_s=dur, is_vertical=vertical,
                                              connection=conn(Destination.LOCAL_EXPORT, True), meta=meta))
        import zipfile
        zpath = Path(local.raw_response.get("bundle_path", ""))
        names = zipfile.ZipFile(zpath).namelist() if zpath.exists() else []
        rows.append({"step": "Local export bundle", "ok": zpath.exists(), "detail": ", ".join(names)})
        rep.expect("Export bundle contains video + caption sheet", "The universal fallback: download & paste.",
                   path.name in names and "caption_and_tags.txt" in names, ", ".join(names))
        rep.visuals.update({
            "rows": rows, "clip": self.rel(path), "zip": self.rel(zpath) if zpath.exists() else None,
            "caption": meta.full_caption_text, "title": meta.title,
        })


def measure_lufs(path: Path) -> Optional[float]:
    """Integrated loudness (LUFS) via FFmpeg's ebur128 meter."""
    res = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0", "-af",
                          "ebur128=framelog=quiet", "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[0-9.]+) LUFS", res.stderr)
    return float(m[-1]) if m else None


def clip_vtt(words, in_s: float, out_s: float, per_group: int = 4) -> str:
    """WebVTT for a rendered clip so the browser preview shows captions even when FFmpeg can't burn them."""
    def ts(x):
        h, rem = divmod(max(0.0, x), 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"
    clip_words = [w for w in words if w.end_s > in_s and w.start_s < out_s]
    lines = ["WEBVTT", ""]
    for g in range(0, len(clip_words), per_group):
        grp = clip_words[g:g + per_group]
        lines += [f"{ts(grp[0].start_s - in_s)} --> {ts(min(out_s, grp[-1].end_s) - in_s)}",
                  " ".join(w.word for w in grp), ""]
    return "\n".join(lines)
