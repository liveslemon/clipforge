"""Tests for Module 10: Social publishing, preflight checks, and idempotency."""
import pytest
from pathlib import Path

from modules.module_10_publishing.models import (
    Destination,
    PublishPrivacy,
    PublishJobState,
    PlatformConnection,
    PostMeta,
)
from modules.module_10_publishing.publisher_service import PublisherService
from modules.module_09_rights_engine.rights_manager import RightsManager
from modules.module_09_rights_engine.models import PermittedUse


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    p = tmp_path / "rendered_clip.mp4"
    p.write_bytes(b"\x00\x00\x00 ftypisom")
    return p


@pytest.mark.asyncio
async def test_youtube_shorts_preflight():
    service = PublisherService()
    yt = service.publishers[Destination.YOUTUBE_SHORTS]

    # 1. Too long (> 180s)
    conn_audited = PlatformConnection(
        id="c1", destination=Destination.YOUTUBE_SHORTS, account_name="yt_user", access_token="tok", is_audited=True
    )
    res_long = await yt.preflight(conn_audited, "dummy.mp4", duration_s=190.0, is_vertical=True)
    assert res_long.eligible is False
    assert res_long.error_code == "duration_exceeded"

    # 2. Unaudited app -> forced private
    conn_unaudited = PlatformConnection(
        id="c2", destination=Destination.YOUTUBE_SHORTS, account_name="yt_user", access_token="tok", is_audited=False
    )
    res_unaudited = await yt.preflight(conn_unaudited, "dummy.mp4", duration_s=45.0, is_vertical=True)
    assert res_unaudited.eligible is True
    assert res_unaudited.forced_privacy == PublishPrivacy.PRIVATE
    assert any("audit" in w.lower() for w in res_unaudited.warnings)


@pytest.mark.asyncio
async def test_publishing_rights_enforcement(sample_file: Path):
    rights_mgr = RightsManager()
    service = PublisherService(rights_manager=rights_mgr)

    conn = PlatformConnection(
        id="c_yt", destination=Destination.YOUTUBE_SHORTS, account_name="yt_user", access_token="tok", is_audited=True
    )
    meta = PostMeta(title="Test Short", caption="Caption text")

    # Attempt to publish without rights -> must fail
    res_no_rights = await service.execute_publish(
        workspace_id="ws_1",
        media_asset_id="med_unauthorized",
        clip_version_id="ver_1",
        media_path=str(sample_file),
        duration_s=30.0,
        is_vertical=True,
        connection=conn,
        meta=meta,
    )
    assert res_no_rights.status == PublishJobState.FAILED
    assert "Rights check failed" in (res_no_rights.error_message or "")

    # Now grant rights
    rights_mgr.register_owner_attestation("ws_1", "med_authorized", "owner_user")
    res_authorized = await service.execute_publish(
        workspace_id="ws_1",
        media_asset_id="med_authorized",
        clip_version_id="ver_1",
        media_path=str(sample_file),
        duration_s=30.0,
        is_vertical=True,
        connection=conn,
        meta=meta,
    )
    assert res_authorized.status == PublishJobState.PUBLISHED
    assert res_authorized.external_post_id is not None


@pytest.mark.asyncio
async def test_publish_idempotency(sample_file: Path):
    rights_mgr = RightsManager()
    rights_mgr.register_owner_attestation("ws_1", "med_1", "owner_user")
    service = PublisherService(rights_manager=rights_mgr)

    conn = PlatformConnection(
        id="c_tiktok", destination=Destination.TIKTOK, account_name="tt_user", access_token="tok", is_audited=True
    )
    meta = PostMeta(title="TikTok Clip", caption="Caption text")

    # First call
    res1 = await service.execute_publish(
        workspace_id="ws_1",
        media_asset_id="med_1",
        clip_version_id="ver_idem",
        media_path=str(sample_file),
        duration_s=25.0,
        is_vertical=True,
        connection=conn,
        meta=meta,
    )
    assert res1.status == PublishJobState.PUBLISHED

    # Second call with same idempotency parameters
    res2 = await service.execute_publish(
        workspace_id="ws_1",
        media_asset_id="med_1",
        clip_version_id="ver_idem",
        media_path=str(sample_file),
        duration_s=25.0,
        is_vertical=True,
        connection=conn,
        meta=meta,
    )
    # Must return exact same result without duplicate publishing
    assert res2.idempotency_key == res1.idempotency_key
    assert res2.external_post_id == res1.external_post_id


@pytest.mark.asyncio
async def test_local_export_packager(sample_file: Path):
    service = PublisherService()
    conn = PlatformConnection(
        id="c_local", destination=Destination.LOCAL_EXPORT, account_name="local", access_token="none"
    )
    meta = PostMeta(title="My Highlight", caption="Best stream moment", hashtags=["stream", "clips"])

    res = await service.execute_publish(
        workspace_id="ws_1",
        media_asset_id="med_1",
        clip_version_id="ver_pack",
        media_path=str(sample_file),
        duration_s=15.0,
        is_vertical=True,
        connection=conn,
        meta=meta,
    )
    assert res.status == PublishJobState.PUBLISHED
    assert res.post_url is not None
    zip_path = Path(res.post_url)
    assert zip_path.exists()
    assert zip_path.suffix == ".zip"
