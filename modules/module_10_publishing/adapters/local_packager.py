"""Universal export packager fallback (Blueprint Section 2.3)."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Optional, List
from ..models import (
    Destination,
    PlatformConnection,
    PostMeta,
    PreflightResult,
    PublishResult,
    PublishJobState,
)


class LocalExportPackager:
    """Creates a standalone export bundle containing the MP4, title/caption copy sheet, and subtitles."""

    destination: Destination = Destination.LOCAL_EXPORT

    async def preflight(
        self,
        conn: PlatformConnection,
        media_path: str,
        duration_s: float,
        is_vertical: bool,
    ) -> PreflightResult:
        # Local export is always eligible
        return PreflightResult(eligible=True, warnings=[])

    async def publish(
        self,
        conn: PlatformConnection,
        media_path: str,
        meta: PostMeta,
        idempotency_key: str,
    ) -> PublishResult:
        src = Path(media_path)
        out_dir = src.parent / f"{src.stem}_export_bundle"
        out_dir.mkdir(parents=True, exist_ok=True)

        # 1. Copy video
        dest_video = out_dir / src.name
        if src.resolve() != dest_video.resolve():
            shutil.copy2(src, dest_video)

        # 2. Write copy-paste caption sheet
        caption_file = out_dir / "caption_and_tags.txt"
        caption_content = (
            f"TITLE:\n{meta.title}\n\n"
            f"CAPTION:\n{meta.caption}\n\n"
            f"HASHTAGS:\n{' '.join('#' + t.lstrip('#') for t in meta.hashtags)}\n\n"
            f"FULL POST TEXT (Ready to paste):\n{meta.full_caption_text}\n"
        )
        caption_file.write_text(caption_content, encoding="utf-8")

        # 3. Create zip package
        zip_path = out_dir.parent / f"{src.stem}_export_bundle.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(dest_video, arcname=dest_video.name)
            z.write(caption_file, arcname=caption_file.name)

        return PublishResult(
            status=PublishJobState.PUBLISHED,
            destination=self.destination,
            idempotency_key=idempotency_key,
            external_post_id=zip_path.name,
            post_url=str(zip_path.resolve()),
            raw_response={"bundle_path": str(zip_path.resolve()), "files_count": 2},
        )

    async def check_status(self, conn: PlatformConnection, external_id: str) -> PublishJobState:
        return PublishJobState.PUBLISHED
