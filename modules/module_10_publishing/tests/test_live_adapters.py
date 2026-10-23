"""Tests for the live TikTok / YouTube / Twitch API request shapes using fake HTTP sessions (no network)."""
from pathlib import Path

import pytest

from modules.module_01_stream_ingest.twitch_client import TwitchAPIError, TwitchClient, clip_slug
from modules.module_10_publishing.adapters.tiktok_publisher import TikTokPublisher, chunk_plan
from modules.module_10_publishing.adapters.youtube_publisher import YouTubeShortsPublisher
from modules.module_10_publishing.models import (
    Destination,
    PlatformConnection,
    PostMeta,
    PublishJobState,
    PublishPrivacy,
)


class FakeResponse:
    def __init__(self, status=200, json_data=None, text=""):
        self.status_code, self._json, self.text = status, json_data or {}, text
        self.content = b"x" if json_data is not None else b""

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _hit(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for key, resp in self.routes.items():
            if key[0] == method and key[1] in url:
                return resp(kw) if callable(resp) else resp
        raise AssertionError(f"unexpected {method} {url}")

    def post(self, url, **kw):
        return self._hit("POST", url, **kw)

    def get(self, url, **kw):
        return self._hit("GET", url, **kw)

    def put(self, url, **kw):
        return self._hit("PUT", url, **kw)


def test_tiktok_chunk_rules():
    assert chunk_plan(3_000_000) == (3_000_000, 1)        # <5 MB: whole file
    assert chunk_plan(64_000_000) == (64_000_000, 1)
    assert chunk_plan(150_000_123) == (10_000_000, 15)    # remainder merged into last chunk


def test_connections_default_to_dry_run():
    conn = PlatformConnection(id="c", destination=Destination.TIKTOK, account_name="a", access_token="t")
    assert conn.dry_run is True


@pytest.mark.asyncio
async def test_tiktok_live_direct_post_unaudited_is_self_only(tmp_path: Path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\0" * 1234)
    session = FakeSession({
        ("POST", "/creator_info/query/"): FakeResponse(json_data={"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]}, "error": {"code": "ok"}}),
        ("POST", "/video/init/"): FakeResponse(json_data={"data": {"publish_id": "p_1", "upload_url": "https://up/x"}, "error": {"code": "ok"}}),
        ("PUT", "https://up/x"): FakeResponse(status=201),
    })
    conn = PlatformConnection(id="c", destination=Destination.TIKTOK, account_name="a", access_token="tok",
                              is_audited=False, dry_run=False)
    res = await TikTokPublisher(session=session).publish(conn, str(clip), PostMeta(title="t", caption="c"), "key")
    assert res.status == PublishJobState.PROCESSING and res.external_post_id == "p_1"
    init = next(kw for m, u, kw in session.calls if u.endswith("/video/init/"))
    assert init["json"]["post_info"]["privacy_level"] == "SELF_ONLY"
    assert init["json"]["source_info"] == {"source": "FILE_UPLOAD", "video_size": 1234, "chunk_size": 1234, "total_chunk_count": 1}
    put = next(kw for m, u, kw in session.calls if m == "PUT")
    assert put["headers"]["Content-Range"] == "bytes 0-1233/1234"
    assert init["json"] and session.calls[0][2]["headers"]["Authorization"] == "Bearer tok"


@pytest.mark.asyncio
async def test_tiktok_api_error_becomes_failed_result(tmp_path: Path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\0" * 10)
    session = FakeSession({("POST", "/creator_info/query/"): FakeResponse(
        status=401, json_data={"error": {"code": "access_token_invalid", "message": "expired"}})})
    conn = PlatformConnection(id="c", destination=Destination.TIKTOK, account_name="a", access_token="bad",
                              is_audited=True, dry_run=False)
    res = await TikTokPublisher(session=session).publish(conn, str(clip), PostMeta(title="t", caption="c"), "k")
    assert res.status == PublishJobState.FAILED and "access_token_invalid" in res.error_message


def test_youtube_body_forces_private_until_audited():
    meta = PostMeta(title="x" * 150, caption="cap", hashtags=["#shorts", "gaming"], privacy=PublishPrivacy.PUBLIC)
    unaudited = PlatformConnection(id="c", destination=Destination.YOUTUBE_SHORTS, account_name="a", access_token="t")
    body = YouTubeShortsPublisher.build_body(unaudited, meta)
    assert body["status"]["privacyStatus"] == "private"
    assert len(body["snippet"]["title"]) == 100 and body["snippet"]["tags"] == ["shorts", "gaming"]
    audited = unaudited.model_copy(update={"is_audited": True})
    assert YouTubeShortsPublisher.build_body(audited, meta)["status"]["privacyStatus"] == "public"


def test_twitch_clip_lookup_uses_helix_with_app_token():
    session = FakeSession({
        ("POST", "id.twitch.tv/oauth2/token"): FakeResponse(json_data={"access_token": "app_tok", "expires_in": 3600}),
        ("GET", "/helix/clips"): FakeResponse(json_data={"data": [{"id": "SleepyClip", "broadcaster_id": "42", "title": "clutch"}]}),
    })
    client = TwitchClient(client_id="cid", client_secret="sec", user_access_token="", session=session)
    assert client.get_clip("https://www.twitch.tv/streamer/clip/SleepyClip")["title"] == "clutch"
    method, url, kw = session.calls[-1]
    assert kw["params"] == {"id": "SleepyClip"} and kw["headers"]["Authorization"] == "Bearer app_tok"
    with pytest.raises(TwitchAPIError, match="TWITCH_USER_ACCESS_TOKEN"):
        client.get_clip_download_urls(["SleepyClip"], "42", "42")


def test_clip_slug_parsing():
    assert clip_slug("https://clips.twitch.tv/FunnyClip-abc_1") == "FunnyClip-abc_1"
    assert clip_slug("RawId") == "RawId"
