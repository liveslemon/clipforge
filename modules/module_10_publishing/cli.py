"""CLI tool for Module 10: Publishing preflight checks and package export."""
from __future__ import annotations

import sys
import json
import asyncio
import argparse
from pathlib import Path

from .models import (
    Destination,
    PlatformConnection,
    PostMeta,
    PublishPrivacy,
)
from .publisher_service import PublisherService
from ..module_09_rights_engine.rights_manager import RightsManager


async def run_publish(dest_name: str, video_path: str, title: str, caption: str, audited: bool):
    dest = Destination(dest_name)
    conn = PlatformConnection(
        id="conn_test",
        destination=dest,
        account_name="test_creator",
        access_token="fake_token",
        is_audited=audited,
    )

    rights_mgr = RightsManager()
    # Mock owner attestation
    rights_mgr.register_owner_attestation("ws_1", "med_1", "user_1")

    service = PublisherService(rights_manager=rights_mgr)
    meta = PostMeta(
        title=title,
        caption=caption,
        hashtags=["gaming", "twitchclips", "clipforge"],
        privacy=PublishPrivacy.PUBLIC,
    )

    res = await service.execute_publish(
        workspace_id="ws_1",
        media_asset_id="med_1",
        clip_version_id="ver_1",
        media_path=video_path,
        duration_s=30.0,
        is_vertical=True,
        connection=conn,
        meta=meta,
    )
    print(res.model_dump_json(indent=2))


def main():
    parser = argparse.ArgumentParser(description="ClipForge Social Publishing CLI")
    parser.add_argument("destination", choices=["youtube_shorts", "tiktok", "local_export"])
    parser.add_argument("video_path", help="Path to rendered MP4 video")
    parser.add_argument("--title", default="Insane Clutch Highlight!")
    parser.add_argument("--caption", default="Best moment from last night's stream")
    parser.add_argument("--audited", action="store_true", help="Simulate approved platform audit")

    args = parser.parse_args()

    asyncio.run(run_publish(args.destination, args.video_path, args.title, args.caption, args.audited))


if __name__ == "__main__":
    main()
