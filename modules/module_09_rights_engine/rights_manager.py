"""Rights and creator authorization manager."""
from __future__ import annotations

import hmac
import hashlib
import json
import base64
import uuid
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta, timezone

from .models import (
    PermittedUse,
    GrantorType,
    ContentRights,
    CreatorGrant,
    RightsCheckResult,
)


class RightsError(Exception):
    pass


class RightsManager:
    """In-memory & database adapter for managing content rights and creator grants."""

    def __init__(self, signing_secret: str = "dev-secret-key-1234567890"):
        self.signing_secret = signing_secret.encode()
        # In-memory storage for module standalone operation
        self.rights_store: Dict[str, ContentRights] = {}
        self.grants_store: Dict[str, CreatorGrant] = {}

    def register_owner_attestation(
        self,
        workspace_id: str,
        media_asset_id: str,
        user_id: str,
        ip_address: Optional[str] = "127.0.0.1",
        permitted_uses: Optional[Set[PermittedUse]] = None,
    ) -> ContentRights:
        """Creates ContentRights for content uploaded directly by the owner."""
        uses = permitted_uses or {
            PermittedUse.EDIT,
            PermittedUse.DOWNLOAD,
            PermittedUse.PUBLISH,
            PermittedUse.COMMERCIAL,
            PermittedUse.MONETIZE,
        }

        rights_id = f"cr_{uuid.uuid4().hex[:8]}"
        record = ContentRights(
            id=rights_id,
            workspace_id=workspace_id,
            media_asset_id=media_asset_id,
            grantor_type=GrantorType.OWNER,
            grantor_user_id=user_id,
            permitted_uses=uses,
            attested_ip=ip_address,
        )
        self.rights_store[rights_id] = record
        return record

    def create_invite_token(
        self,
        creator_user_id: str,
        channels: List[str],
        permitted_uses: Set[PermittedUse],
        valid_days: int = 14,
    ) -> str:
        """Generates a tamper-proof HMAC-signed invite token (14-day expiry per Blueprint Section 3.8)."""
        payload = {
            "creator_user_id": creator_user_id,
            "channels": channels,
            "permitted_uses": [u.value for u in permitted_uses],
            "exp": (datetime.now(timezone.utc) + timedelta(days=valid_days)).timestamp(),
            "nonce": uuid.uuid4().hex[:6],
        }
        raw_json = json.dumps(payload, sort_keys=True)
        payload_b64 = base64.urlsafe_b64encode(raw_json.encode()).decode().rstrip("=")

        sig = hmac.new(self.signing_secret, payload_b64.encode(), hashlib.sha256).hexdigest()
        return f"{payload_b64}.{sig}"

    def claim_invite_token(
        self,
        token: str,
        grantee_workspace_id: str,
    ) -> CreatorGrant:
        """Verifies HMAC signature and claims a creator grant for an editor's workspace."""
        try:
            payload_b64, sig = token.split(".")
        except ValueError:
            raise RightsError("Invalid token format.")

        expected_sig = hmac.new(self.signing_secret, payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise RightsError("Token signature verification failed.")

        # Decode payload
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        raw_json = base64.urlsafe_b64decode(padded.encode()).decode()
        data = json.loads(raw_json)

        exp = datetime.fromtimestamp(data["exp"], tz=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            raise RightsError("Invite token has expired.")

        grant_id = f"grant_{uuid.uuid4().hex[:8]}"
        grant = CreatorGrant(
            id=grant_id,
            creator_user_id=data["creator_user_id"],
            grantee_workspace_id=grantee_workspace_id,
            channels=data["channels"],
            permitted_uses={PermittedUse(u) for u in data["permitted_uses"]},
            expires_at=exp,
        )
        self.grants_store[grant_id] = grant
        return grant

    def grant_rights_to_media(
        self,
        grant_id: str,
        media_asset_id: str,
    ) -> ContentRights:
        """Binds an active CreatorGrant to a specific media asset in the editor's workspace."""
        grant = self.grants_store.get(grant_id)
        if not grant or not grant.is_active:
            raise RightsError("Creator grant not found or inactive.")

        rights_id = f"cr_{uuid.uuid4().hex[:8]}"
        record = ContentRights(
            id=rights_id,
            workspace_id=grant.grantee_workspace_id,
            media_asset_id=media_asset_id,
            grantor_type=GrantorType.CREATOR_GRANT,
            grantor_user_id=grant.creator_user_id,
            permitted_uses=grant.permitted_uses,
            expires_at=grant.expires_at,
        )
        self.rights_store[rights_id] = record
        return record

    def revoke_rights(self, rights_id: str):
        """Immediately revokes a rights grant."""
        if rights_id in self.rights_store:
            self.rights_store[rights_id].revoked_at = datetime.now(timezone.utc)

    def check_permission(
        self,
        workspace_id: str,
        media_asset_id: str,
        requested_use: PermittedUse,
    ) -> RightsCheckResult:
        """Checks if a workspace is authorized to perform requested_use on media_asset_id."""
        matching = [
            r for r in self.rights_store.values()
            if r.workspace_id == workspace_id and r.media_asset_id == media_asset_id
        ]

        if not matching:
            return RightsCheckResult(
                allowed=False,
                requested_use=requested_use,
                media_asset_id=media_asset_id,
                workspace_id=workspace_id,
                reason="No content_rights record found for this asset and workspace.",
            )

        active_rights = [r for r in matching if r.is_active]
        if not active_rights:
            return RightsCheckResult(
                allowed=False,
                requested_use=requested_use,
                media_asset_id=media_asset_id,
                workspace_id=workspace_id,
                reason="All content_rights records for this asset have expired or been revoked.",
            )

        # Check if any active rights grant covers requested_use
        for r in active_rights:
            if requested_use in r.permitted_uses:
                return RightsCheckResult(
                    allowed=True,
                    requested_use=requested_use,
                    media_asset_id=media_asset_id,
                    workspace_id=workspace_id,
                    reason=f"Authorized via active {r.grantor_type.value}.",
                    active_rights_id=r.id,
                )

        return RightsCheckResult(
            allowed=False,
            requested_use=requested_use,
            media_asset_id=media_asset_id,
            workspace_id=workspace_id,
            reason=f"Requested use '{requested_use.value}' is not included in permitted uses.",
        )
