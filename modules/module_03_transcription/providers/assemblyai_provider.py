"""AssemblyAI async transcription provider (Universal-3.5 Pro with Universal-2 fallback).

Uses the current /v2/transcript API: `speech_models`, a free-text `prompt` describing the audio (steers
ambiguous words toward ones that fit the context) and `keyterms_prompt` for names/jargon.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import List, Optional

import requests

from ...config import get_settings
from ..models import TimedWord, Transcript, TranscriptSegment

BASE_URL = "https://api.assemblyai.com/v2"
SPEECH_MODELS = ["universal-3-5-pro", "universal-2"]  # first available model wins
MAX_KEYTERMS = 1000
MAX_PROMPT_WORDS = 1500


class AssemblyAIProviderError(Exception):
    pass


class AssemblyAIProvider:
    name: str = "assemblyai"

    def __init__(self, api_key: Optional[str] = None, context: Optional[str] = None, poll_interval_s: float = 3.0):
        """context: what the audio is about (topic, who's speaking, setting) — sent as AssemblyAI's `prompt`."""
        self.api_key = api_key or get_settings().assemblyai_api_key
        self.context = (context or "").strip()
        self.poll_interval_s = poll_interval_s
        self.session = requests.Session()

    def build_request(self, audio_url: str, language: Optional[str], vocabulary: Optional[List[str]]) -> dict:
        payload = {
            "audio_url": audio_url,
            "speech_models": SPEECH_MODELS,
            "speaker_labels": True,
            "punctuate": True,
            "format_text": True,
        }
        if language and language != "auto":
            payload["language_code"] = language
        else:
            payload["language_detection"] = True
        if self.context:
            payload["prompt"] = " ".join(self.context.split()[:MAX_PROMPT_WORDS])
        terms = [t.strip() for t in (vocabulary or []) if t.strip() and len(t.split()) <= 6]
        if terms:
            payload["keyterms_prompt"] = terms[:MAX_KEYTERMS]
        return payload

    async def transcribe(
        self,
        audio_path_or_url: str,
        *,
        language: Optional[str] = "en",
        vocabulary: Optional[List[str]] = None,
        on_progress = None,
    ) -> Transcript:
        return await asyncio.to_thread(self._transcribe_sync, audio_path_or_url, language, vocabulary, on_progress)

    def _transcribe_sync(
        self,
        audio_path_or_url: str,
        language: Optional[str],
        vocabulary: Optional[List[str]],
        on_progress = None,
    ) -> Transcript:
        if not self.api_key:
            raise AssemblyAIProviderError("ASSEMBLYAI_API_KEY is not configured.")
        headers = {"authorization": self.api_key}

        audio_url = audio_path_or_url
        if Path(audio_path_or_url).exists():
            if on_progress:
                on_progress("Uploading audio to AssemblyAI cloud…")
            with open(audio_path_or_url, "rb") as f:
                up = self.session.post(f"{BASE_URL}/upload", headers=headers, data=f, timeout=600)
            self._raise_for(up, "upload")
            audio_url = up.json()["upload_url"]

        if on_progress:
            on_progress("Submitting transcription job to AssemblyAI…")
        sub = self.session.post(f"{BASE_URL}/transcript", json=self.build_request(audio_url, language, vocabulary),
                                headers=headers, timeout=60)
        self._raise_for(sub, "submit")
        transcript_id = sub.json()["id"]

        t0 = time.time()
        max_wait_s = 240.0
        while True:
            if time.time() - t0 > max_wait_s:
                raise AssemblyAIProviderError(f"AssemblyAI timed out after {int(max_wait_s)}s polling transcript {transcript_id}")
            poll = self.session.get(f"{BASE_URL}/transcript/{transcript_id}", headers=headers, timeout=60)
            self._raise_for(poll, "poll")
            data = poll.json()
            status = data.get("status")
            if on_progress:
                on_progress(f"AssemblyAI processing ({status}, {int(time.time() - t0)}s elapsed)…")
            if status == "completed":
                break
            if status == "error":
                raise AssemblyAIProviderError(f"AssemblyAI failed: {data.get('error')}")
            time.sleep(self.poll_interval_s)

        return self.parse_response(data, audio_path_or_url)

    @staticmethod
    def _raise_for(res: requests.Response, step: str) -> None:
        if res.status_code >= 400:
            raise AssemblyAIProviderError(f"AssemblyAI {step} failed ({res.status_code}): {res.text[:500]}")

    def parse_response(self, data: dict, media_id: str) -> Transcript:
        def words_of(items) -> List[TimedWord]:
            return [TimedWord(word=w.get("text", ""), start_ms=int(w.get("start", 0)), end_ms=int(w.get("end", 0)),
                              confidence=float(w.get("confidence", 1.0))) for w in items or []]

        segments: List[TranscriptSegment] = []
        for idx, utt in enumerate(data.get("utterances") or []):
            segments.append(TranscriptSegment(
                id=idx + 1, start_ms=int(utt.get("start", 0)), end_ms=int(utt.get("end", 0)),
                text=utt.get("text", ""), speaker=utt.get("speaker"),
                confidence=float(utt.get("confidence", 1.0)), words=words_of(utt.get("words")),
            ))
        if not segments and data.get("words"):
            words = words_of(data["words"])
            segments.append(TranscriptSegment(id=1, start_ms=words[0].start_ms, end_ms=words[-1].end_ms,
                                              text=data.get("text", ""), words=words))

        return Transcript(
            media_id=media_id,
            provider=f"{self.name}:{data.get('speech_model_used') or data.get('speech_model') or SPEECH_MODELS[0]}",
            language=data.get("language_code") or "en",
            duration_seconds=float(data.get("audio_duration") or 0.0),
            full_text=data.get("text", ""),
            segments=segments,
            raw_metadata={"transcript_id": data.get("id"), "context_used": bool(self.context),
                          "low_confidence_words": sum(w.confidence < 0.5 for s in segments for w in s.words)},
        )
