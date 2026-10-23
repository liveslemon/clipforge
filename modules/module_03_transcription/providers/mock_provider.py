"""Deterministic mock transcription provider for testing and offline development."""
from __future__ import annotations

import re
from typing import Optional, List
from ..models import Transcript, TranscriptSegment, TimedWord


class MockTranscriptionProvider:
    name: str = "mock-stt"

    def __init__(self, sample_script: Optional[List[dict]] = None):
        self.sample_script = sample_script

    async def transcribe(
        self,
        audio_path_or_url: str,
        *,
        language: Optional[str] = "en",
        vocabulary: Optional[List[str]] = None,
    ) -> Transcript:
        # Default mock stream speech script
        script = self.sample_script or [
            {
                "speaker": "Streamer",
                "text": "Yo chat welcome in! Today we are trying out the new update.",
                "start_ms": 500,
            },
            {
                "speaker": "Streamer",
                "text": "Wait what was that noise? Did you hear that?",
                "start_ms": 4200,
            },
            {
                "speaker": "Streamer",
                "text": "Oh my god no way! Look at the leaderboard right now!",
                "start_ms": 7800,
            },
            {
                "speaker": "Streamer",
                "text": "Clip that right now! That was insane!",
                "start_ms": 11500,
            },
        ]

        segments: List[TranscriptSegment] = []
        all_text_parts: List[str] = []

        for idx, item in enumerate(script):
            text = item["text"]
            seg_start = item["start_ms"]
            speaker = item.get("speaker", "Streamer")
            all_text_parts.append(text)

            words = text.split()
            word_dur = 320  # average 320ms per word
            timed_words: List[TimedWord] = []

            curr_ms = seg_start
            for w in words:
                clean_w = re.sub(r"[^\w\s']", "", w)
                end_ms = curr_ms + word_dur
                timed_words.append(
                    TimedWord(
                        word=clean_w or w,
                        start_ms=curr_ms,
                        end_ms=end_ms,
                        confidence=0.98,
                    )
                )
                curr_ms = end_ms + 40  # 40ms inter-word gap

            seg_end = curr_ms
            segments.append(
                TranscriptSegment(
                    id=idx + 1,
                    start_ms=seg_start,
                    end_ms=seg_end,
                    text=text,
                    speaker=speaker,
                    confidence=0.98,
                    words=timed_words,
                )
            )

        duration_s = (segments[-1].end_ms / 1000.0) if segments else 0.0

        return Transcript(
            media_id=audio_path_or_url,
            provider=self.name,
            language=language or "en",
            duration_seconds=duration_s,
            full_text=" ".join(all_text_parts),
            segments=segments,
            raw_metadata={"mock": True},
        )
