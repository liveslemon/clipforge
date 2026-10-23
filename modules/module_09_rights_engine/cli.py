"""CLI tool for Module 9: Rights management and creator invite generation."""
from __future__ import annotations

import sys
import json
import argparse

from .rights_manager import RightsManager
from .models import PermittedUse


def main():
    parser = argparse.ArgumentParser(description="ClipForge Rights Engine CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-invite
    inv_parser = subparsers.add_parser("create-invite", help="Generate a signed creator invite link")
    inv_parser.add_argument("creator_id", help="Creator user ID")
    inv_parser.add_argument("channels", nargs="+", help="Channel names/IDs (e.g. shroud tarik)")
    inv_parser.add_argument("--days", type=int, default=14, help="Validity in days (default: 14)")

    # check-rights
    check_parser = subparsers.add_parser("check", help="Check permission on an asset")
    check_parser.add_argument("workspace_id")
    check_parser.add_argument("media_id")
    check_parser.add_argument("use", choices=[u.value for u in PermittedUse])

    args = parser.parse_args()

    manager = RightsManager()

    if args.command == "create-invite":
        uses = {PermittedUse.EDIT, PermittedUse.DOWNLOAD, PermittedUse.PUBLISH}
        token = manager.create_invite_token(args.creator_id, args.channels, uses, args.days)
        print("Generated Signed Creator Invite Link:")
        print(f"https://app.clipforge.app/claim?token={token}")

    elif args.command == "check":
        res = manager.check_permission(args.workspace_id, args.media_id, PermittedUse(args.use))
        print(res.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
