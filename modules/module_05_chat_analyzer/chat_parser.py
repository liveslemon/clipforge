"""Parsers for stream chat logs (Twitch IRC, timecoded text, JSON)."""
from __future__ import annotations

import re
import json
from pathlib import Path
from typing import List, Optional

from .models import ChatMessage

KNOWN_EMOTES = {
    "kekw", "lul", "pog", "pogchamp", "omegalul", "monkas", "pepehands",
    "pepega", "5head", "kappa", "trihard", "ayaya", "ez", "gg", "w", "l"
}


def parse_timestamp_str(time_str: str) -> float:
    """Parses timestamps like 01:23:45 or 04:12 or 12.5s to float seconds."""
    time_str = time_str.strip().rstrip("s")
    parts = time_str.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    else:
        return float(time_str)


class ChatParser:
    """Parses chat messages from strings, files, or JSON structures."""

    @staticmethod
    def extract_emotes(text: str) -> List[str]:
        words = re.findall(r"\b\w+\b", text.lower())
        return [w for w in words if w in KNOWN_EMOTES]

    @classmethod
    def from_json_file(cls, json_path: str | Path) -> List[ChatMessage]:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        messages: List[ChatMessage] = []
        for item in data:
            ts = float(item.get("timestamp_s", item.get("time", item.get("offset", 0.0))))
            author = item.get("author", item.get("user", item.get("username", "anonymous")))
            text = item.get("text", item.get("message", item.get("body", "")))
            emotes = cls.extract_emotes(text)
            messages.append(ChatMessage(timestamp_s=ts, author=author, text=text, emotes=emotes))
        return sorted(messages, key=lambda m: m.timestamp_s)

    @classmethod
    def from_text_lines(cls, lines: List[str]) -> List[ChatMessage]:
        """Parses lines in formats such as:

        [00:01:23] user: hello world
        [14.5s] user: LMAO
        """
        messages: List[ChatMessage] = []
        pattern = re.compile(r"^\[([0-9:.]+)s?\]\s*([^:]+):\s*(.*)$")

        for line in lines:
            line = line.strip()
            match = pattern.match(line)
            if match:
                time_str, author, text = match.groups()
                try:
                    ts = parse_timestamp_str(time_str)
                    emotes = cls.extract_emotes(text)
                    messages.append(ChatMessage(timestamp_s=ts, author=author.strip(), text=text.strip(), emotes=emotes))
                except ValueError:
                    continue
        return sorted(messages, key=lambda m: m.timestamp_s)

    @classmethod
    def from_file(cls, file_path: str | Path) -> List[ChatMessage]:
        p = Path(file_path)
        if p.suffix.lower() == ".json":
            return cls.from_json_file(p)
        else:
            lines = p.read_text(encoding="utf-8").splitlines()
            return cls.from_text_lines(lines)
