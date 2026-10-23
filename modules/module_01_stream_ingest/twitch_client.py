"""Official Twitch Helix client: clip metadata and authorised clip downloads (no scraping, per the blueprint).

Endpoints (dev.twitch.tv/docs/api/reference):
  POST https://id.twitch.tv/oauth2/token          client-credentials app access token
  GET  https://api.twitch.tv/helix/clips          clip metadata (app token is enough)
  GET  https://api.twitch.tv/helix/videos         VOD metadata
  GET  https://api.twitch.tv/helix/clips/downloads  download URLs; token needs editor:manage:clips or
                                                    channel:manage:clips, editor_id must match the token's user
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

import requests

from ..config import get_settings

HELIX = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"


class TwitchAPIError(Exception):
    pass


def clip_slug(clip_url_or_id: str) -> str:
    m = re.search(r"(?:clips\.twitch\.tv/|/clip/)([A-Za-z0-9_-]+)", clip_url_or_id)
    return m.group(1) if m else clip_url_or_id.strip()


class TwitchClient:
    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None,
                 user_access_token: Optional[str] = None, session: Optional[requests.Session] = None):
        s = get_settings()
        self.client_id = client_id or s.twitch_client_id
        self.client_secret = client_secret or s.twitch_client_secret
        self.user_token = user_access_token or s.twitch_user_access_token
        self.session = session or requests.Session()
        self._app_token: Optional[str] = None
        self._app_token_expiry = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and (self.client_secret or self.user_token))

    def app_token(self) -> str:
        if self._app_token and time.time() < self._app_token_expiry - 60:
            return self._app_token
        if not (self.client_id and self.client_secret):
            raise TwitchAPIError("TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET are required.")
        res = self.session.post(TOKEN_URL, params={"client_id": self.client_id, "client_secret": self.client_secret,
                                                   "grant_type": "client_credentials"}, timeout=15)
        if res.status_code != 200:
            raise TwitchAPIError(f"Twitch token request failed ({res.status_code}): {res.text[:300]}")
        data = res.json()
        self._app_token = data["access_token"]
        self._app_token_expiry = time.time() + float(data.get("expires_in", 3600))
        return self._app_token

    def _get(self, path: str, params, token: Optional[str] = None) -> List[Dict]:
        token = token or self.app_token()
        res = self.session.get(f"{HELIX}{path}", params=params, timeout=15,
                               headers={"Client-Id": self.client_id, "Authorization": f"Bearer {token}"})
        if res.status_code != 200:
            raise TwitchAPIError(f"Twitch {path} failed ({res.status_code}): {res.text[:300]}")
        return res.json().get("data", [])

    def get_clip(self, clip_url_or_id: str) -> Dict:
        data = self._get("/clips", {"id": clip_slug(clip_url_or_id)})
        if not data:
            raise TwitchAPIError(f"Clip not found: {clip_url_or_id}")
        return data[0]

    def get_video(self, video_id: str) -> Dict:
        data = self._get("/videos", {"id": video_id})
        if not data:
            raise TwitchAPIError(f"VOD not found: {video_id}")
        return data[0]

    def get_clip_download_urls(self, clip_ids: List[str], broadcaster_id: str, editor_id: str) -> List[Dict]:
        """Needs a user token (broadcaster or editor) with editor:manage:clips / channel:manage:clips."""
        if not self.user_token:
            raise TwitchAPIError("Clip downloads need TWITCH_USER_ACCESS_TOKEN from the broadcaster or an editor "
                                 "with the editor:manage:clips or channel:manage:clips scope.")
        params = [("broadcaster_id", broadcaster_id), ("editor_id", editor_id)] + [("clip_id", c) for c in clip_ids[:10]]
        return self._get("/clips/downloads", params, token=self.user_token)
