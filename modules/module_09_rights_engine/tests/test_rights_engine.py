"""Tests for Module 9: Content rights, creator authorization, and HMAC invite tokens."""
import pytest
from datetime import datetime, timedelta, timezone

from modules.module_09_rights_engine.models import (
    PermittedUse,
    GrantorType,
    ContentRights,
    RightsCheckResult,
)
from modules.module_09_rights_engine.rights_manager import (
    RightsManager,
    RightsError,
)


def test_owner_attestation_and_permission_check():
    mgr = RightsManager()

    # 1. Check before rights are registered -> must be blocked
    res1 = mgr.check_permission("ws_100", "med_500", PermittedUse.EDIT)
    assert res1.allowed is False
    assert "No content_rights record found" in res1.reason

    # 2. Register owner attestation
    rights = mgr.register_owner_attestation("ws_100", "med_500", "user_1")
    assert rights.is_active is True

    # 3. Check again -> allowed!
    res2 = mgr.check_permission("ws_100", "med_500", PermittedUse.EDIT)
    assert res2.allowed is True
    assert "Authorized via active owner" in res2.reason

    # 4. Check download and publish -> allowed
    assert mgr.check_permission("ws_100", "med_500", PermittedUse.DOWNLOAD).allowed is True
    assert mgr.check_permission("ws_100", "med_500", PermittedUse.PUBLISH).allowed is True


def test_creator_invite_token_workflow():
    mgr = RightsManager(signing_secret="super-secret-key")

    # 1. Creator generates invite token for their channel "shroud"
    token = mgr.create_invite_token(
        creator_user_id="creator_shroud",
        channels=["shroud"],
        permitted_uses={PermittedUse.EDIT, PermittedUse.DOWNLOAD},
        valid_days=14,
    )
    assert "." in token

    # 2. Editor in workspace "ws_editor" claims token
    grant = mgr.claim_invite_token(token, grantee_workspace_id="ws_editor")
    assert grant.creator_user_id == "creator_shroud"
    assert grant.grantee_workspace_id == "ws_editor"
    assert PermittedUse.EDIT in grant.permitted_uses
    assert PermittedUse.PUBLISH not in grant.permitted_uses  # Publish not granted

    # 3. Bind grant to media asset
    rights = mgr.grant_rights_to_media(grant.id, "med_shroud_clip_1")

    # 4. Check permissions
    assert mgr.check_permission("ws_editor", "med_shroud_clip_1", PermittedUse.EDIT).allowed is True
    assert mgr.check_permission("ws_editor", "med_shroud_clip_1", PermittedUse.DOWNLOAD).allowed is True
    # Publish should be denied because creator only granted EDIT and DOWNLOAD
    pub_res = mgr.check_permission("ws_editor", "med_shroud_clip_1", PermittedUse.PUBLISH)
    assert pub_res.allowed is False
    assert "not included in permitted uses" in pub_res.reason


def test_tampered_or_expired_token():
    mgr = RightsManager()
    token = mgr.create_invite_token("creator_1", ["channel1"], {PermittedUse.EDIT}, valid_days=14)

    # Tamper with token
    payload_b64, sig = token.split(".")
    tampered_token = f"{payload_b64}X.{sig}"
    with pytest.raises(RightsError, match="Token signature verification failed"):
        mgr.claim_invite_token(tampered_token, "ws_2")

    # Expired token (-1 days)
    expired_token = mgr.create_invite_token("creator_1", ["channel1"], {PermittedUse.EDIT}, valid_days=-1)
    with pytest.raises(RightsError, match="Invite token has expired"):
        mgr.claim_invite_token(expired_token, "ws_2")


def test_revocation():
    mgr = RightsManager()
    rights = mgr.register_owner_attestation("ws_1", "med_1", "user_1")
    assert mgr.check_permission("ws_1", "med_1", PermittedUse.EDIT).allowed is True

    # Revoke rights
    mgr.revoke_rights(rights.id)
    assert rights.is_active is False

    # Check permission after revocation
    res = mgr.check_permission("ws_1", "med_1", PermittedUse.EDIT)
    assert res.allowed is False
    assert "revoked" in res.reason
