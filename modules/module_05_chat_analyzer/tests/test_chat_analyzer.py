"""Tests for Module 5: Chat parsing, velocity calculation, and reaction scoring."""
import json
import pytest
from pathlib import Path

from modules.module_05_chat_analyzer.models import ChatMessage, ChatScore
from modules.module_05_chat_analyzer.chat_parser import ChatParser, parse_timestamp_str
from modules.module_05_chat_analyzer.velocity_engine import ChatVelocityEngine


def test_parse_timestamp_str():
    assert parse_timestamp_str("12.5s") == 12.5
    assert parse_timestamp_str("01:30") == 90.0
    assert parse_timestamp_str("01:02:03") == 3723.0


def test_chat_parser_text_lines():
    lines = [
        "[00:00:05] user1: hey everyone welcome in",
        "[00:00:10] user2: KEKW that was so funny lul",
        "[15.5s] user3: CLIP THAT RIGHT NOW POG",
    ]
    messages = ChatParser.from_text_lines(lines)

    assert len(messages) == 3
    assert messages[0].timestamp_s == 5.0
    assert messages[0].author == "user1"

    # Emotes parsed
    assert "kekw" in messages[1].emotes
    assert "lul" in messages[1].emotes
    assert "pog" in messages[2].emotes


def test_chat_parser_json(tmp_path: Path):
    data = [
        {"timestamp_s": 2.0, "author": "alice", "text": "yo"},
        {"timestamp_s": 4.5, "author": "bob", "text": "gg wp"},
    ]
    json_file = tmp_path / "chat.json"
    json_file.write_text(json.dumps(data))

    messages = ChatParser.from_json_file(json_file)
    assert len(messages) == 2
    assert messages[0].author == "alice"
    assert "gg" in messages[1].emotes


def test_chat_velocity_and_spike_scoring():
    # 1. Create a quiet baseline: 1 msg every 4 seconds from t=0 to t=40s
    messages = []
    for t in range(0, 40, 4):
        messages.append(ChatMessage(timestamp_s=float(t), author="viewer", text="nice game"))

    # 2. Add an intense reaction burst at t=16s to t=19s (simulating stream event at t=11s with 5s lag)
    # 20 messages in 3 seconds!
    for _ in range(20):
        messages.append(
            ChatMessage(
                timestamp_s=16.5,
                author="hyped_viewer",
                text="OMGGG KEKW KEKW CLIP IT BRO POG",
                emotes=["kekw", "kekw", "pog"],
            )
        )
    messages = sorted(messages, key=lambda m: m.timestamp_s)

    engine = ChatVelocityEngine(window_size_s=5.0, lag_compensation_s=5.0)
    timeline, mean_rate, std_rate = engine.compute_timeline(messages)

    assert mean_rate > 0
    assert std_rate > 0

    # 3. Score an on-stream window around t=11s (event happens at 11s, chat explodes at 16s)
    score = engine.score_window(messages, on_stream_start_s=10.0, on_stream_end_s=13.0, mean_rate=mean_rate, std_rate=std_rate)

    assert score.score > 0.6  # High S_chat score
    assert score.has_clip_it_trigger is True  # Detected "CLIP IT"
    assert score.peak_msg_rate > mean_rate * 3  # Clear spike
    assert "kekw" in score.top_emotes

    # 4. Score a quiet window at t=30s
    quiet_score = engine.score_window(messages, on_stream_start_s=28.0, on_stream_end_s=32.0, mean_rate=mean_rate, std_rate=std_rate)
    assert quiet_score.score < 0.25
    assert quiet_score.has_clip_it_trigger is False
